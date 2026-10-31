"""Downloading one channel: find what is new, fetch each file safely, never stop for one bad file."""
from __future__ import annotations

import asyncio
import errno
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from telethon.errors import FileReferenceExpiredError, FloodWaitError
from telethon.tl.types import (InputMessagesFilterDocument, InputMessagesFilterMusic, InputMessagesFilterPhotoVideo,
                               InputMessagesFilterRoundVideo, InputMessagesFilterVoice)

from . import paths
from .errors import UserError, friendly
from .library import Library, chunked, fold
from .naming import (AUDIO_EXT_BY_MIME, build_filename, classify, fingerprint, human_size, is_real_pdf,
                     mark_downloaded, other_extension, sanitize, split_name, unique_path)
from .topics import OTHER, Sections, sort_channel

log = logging.getLogger("tajmeea")
Emit = Callable[[str, Dict[str, Any]], None]
RETRY_DELAYS = (3, 10, 30)
PARALLEL = 3  # files downloading at once; Telegram's own apps do about the same
SPACE_RESERVE = 300 * 1024 * 1024  # never fill the drive to the last byte
RESUME_STEP = 512 * 1024  # a cut-off file continues from a multiple of Telegram's largest request


@dataclass
class Filters:
    """What the person narrowed a channel to: a date range, words that must appear, a size limit."""
    since: str = ""  # YYYY-MM-DD, both ends included
    until: str = ""
    words: str = ""
    max_mb: int = 0

    @classmethod
    def of(cls, saved: Optional[Dict[str, Any]]) -> "Filters":
        saved = saved or {}
        return cls(saved.get("since") or "", saved.get("until") or "", saved.get("words") or "",
                   int(saved.get("maxMb") or 0))

    def allows(self, info: Dict[str, Any]) -> bool:
        day = info["date"].date().isoformat() if info["date"] else ""
        if day and ((self.since and day < self.since) or (self.until and day > self.until)):
            return False
        if self.max_mb and info["size"] > self.max_mb * 1024 * 1024:
            return False
        text = fold(f"{info['name']} {info['caption']}")
        return all(word in text for word in fold(self.words).split())


@dataclass
class JobOptions:
    kinds: Set[str]
    folder: Path
    year_folders: bool = True
    smart_names: bool = True
    topic_folders: bool = False
    restore_missing: bool = False
    filters: Filters = field(default_factory=Filters)
    parallel: int = PARALLEL
    skip_exts: Set[str] = field(default_factory=set)  # «other» formats the person turned off, like ".psd"


@dataclass
class Progress:
    state: str = "queued"
    total: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    rejected: int = 0
    bytes_total: int = 0
    bytes_done: int = 0
    speed: float = 0.0
    wait_until: float = 0.0
    current: Optional[Dict[str, Any]] = None
    active: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""
    error_code: str = ""
    started: float = field(default_factory=time.time)

    def snapshot(self) -> Dict[str, Any]:
        remaining = max(0, self.bytes_total - self.bytes_done)
        return {
            "state": self.state,
            "total": self.total,
            "done": self.done,
            "skipped": self.skipped,
            "failed": self.failed,
            "rejected": self.rejected,
            "processed": self.done + self.skipped + self.failed + self.rejected,
            "bytesTotal": self.bytes_total,
            "bytesDone": self.bytes_done,
            "speed": round(self.speed),
            "eta": round(remaining / self.speed) if self.speed > 1 else None,
            "waitSeconds": max(0, round(self.wait_until - time.time())) if self.state == "waiting" else 0,
            "current": dict(self.current) if self.current else None,
            "active": [dict(item) for item in self.active],
            "error": self.error,
            "errorCode": self.error_code,
        }


async def iter_documents(client: Any, entity: Any, min_id: int, on_wait: Callable[[int], Awaitable[None]],
                         message_filter: Any = InputMessagesFilterDocument):
    """All messages of one kind newer than min_id, oldest first, carrying on after Telegram asks us to wait."""
    cursor = min_id
    while True:
        try:
            async for message in client.iter_messages(entity, min_id=cursor, reverse=True, filter=message_filter):
                cursor = max(cursor, message.id)
                yield message
            return
        except FloodWaitError as exc:
            await on_wait(exc.seconds)


# Telegram files each sort of post in its own list: tracks and voice notes are not under "files".
# Files are always read; the others only when what they hold was chosen.
FILTERS = (
    (InputMessagesFilterDocument, None),
    (InputMessagesFilterMusic, {"audio"}),
    (InputMessagesFilterVoice, {"voice"}),
    (InputMessagesFilterPhotoVideo, {"images", "videos"}),
    (InputMessagesFilterRoundVideo, {"videos"}),
)


async def iter_files(client: Any, entity: Any, min_id: int, on_wait: Callable[[int], Awaitable[None]],
                     kinds: Optional[Set[str]] = None):
    """Every post that may hold a wanted file; all lists when kinds is None (a full scan).
    A post can come from more than one list; callers keep the first by id."""
    for message_filter, holds in FILTERS:
        if holds is None or kinds is None or holds & kinds:
            async for message in iter_documents(client, entity, min_id, on_wait, message_filter):
                yield message


def describe(message: Any) -> Dict[str, Any]:
    """What a post holds. kind is None for stickers and GIFs, and "blocked" for programs we never save."""
    file = getattr(message, "file", None)
    name = getattr(file, "name", None) or ""
    mime = getattr(file, "mime_type", None) or ""
    media = getattr(message, "document", None) or getattr(message, "photo", None)
    ext = ""
    if getattr(message, "sticker", None) or getattr(message, "gif", None):
        kind = None
    elif getattr(message, "voice", None):
        kind, mime = "voice", mime or "audio/ogg"
        name = name or f"بصمة {message.id}.ogg"
    elif getattr(message, "video_note", None):
        kind, mime = "videos", mime or "video/mp4"
        name = name or f"فيديو {message.id}.mp4"
    else:
        kind = classify(mime, name)
        if kind is None and getattr(message, "photo", None):
            kind, mime = "images", mime or "image/jpeg"
        elif kind is None and getattr(message, "document", None):
            kept = other_extension(name)
            kind, ext = ("other", kept) if kept is not None else ("blocked", split_name(name)[1])
    if kind == "audio" and not name:
        # A track carries a singer and title instead of a file name.
        label = " - ".join(p for p in (getattr(file, "performer", None), getattr(file, "title", None)) if p)
        if label:
            name = label + AUDIO_EXT_BY_MIME.get(mime.lower(), ".mp3")
    return {
        "ext": ext,
        "msg_id": message.id,
        "doc_id": getattr(media, "id", 0) or 0,
        "name": name,
        "mime": mime,
        "size": getattr(file, "size", 0) or 0,
        "kind": kind,
        "date": message.date,
        "caption": getattr(message, "message", "") or "",
    }


class DownloadJob:
    def __init__(
        self,
        *,
        channel: Dict[str, Any],
        entity: Any,
        client: Any,
        library: Library,
        emit: Emit,
        options: JobOptions,
        prefetched: Optional[List[Any]] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        after_file: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.after_file = after_file
        self.sections = Sections([])
        self.channel = channel
        self.entity = entity
        self.client = client
        self.library = library
        self.emit = emit
        self.options = options
        self.prefetched = prefetched
        self.sleep = sleep
        self.progress = Progress()
        self._paused = False
        self._resume: Optional[asyncio.Event] = None  # made inside run(), on the loop that runs it
        self._last_emit = 0.0
        self._speed_mark = (time.monotonic(), 0)
        self._active: Dict[int, Dict[str, Any]] = {}  # files downloading right now, by message id
        self._settled = 0  # bytes of files that are finished one way or another
        self._claimed: Set[Path] = set()  # names being written right now, so two files never share one

    # Controls

    def pause(self) -> None:
        if self.progress.state in ("queued", "running", "scanning", "waiting"):
            self._paused = True
            if self._resume:
                self._resume.clear()
            self._set_state("paused")

    def resume(self) -> None:
        if self._paused:
            self._paused = False
            if self._resume:
                self._resume.set()
            self._set_state("running")

    async def _gate(self) -> None:
        if self._paused and self._resume:
            await self._resume.wait()

    # Running

    async def run(self) -> Dict[str, Any]:
        self._resume = asyncio.Event()
        if not self._paused:
            self._resume.set()
        try:
            self._set_state("paused" if self._paused else "scanning")
            plan, newest_id = await self._plan()
            self.progress.total = len(plan)
            self.progress.bytes_total = sum(item["size"] for item in plan)
            self._check_space()
            self._set_state("paused" if self._paused else "running")

            again = await self._fetch_all(plan, last_try=False)
            await self._fetch_all(again, last_try=True)

            self.library.mark_synced(self.channel["id"], newest_id)
            self.library.export_index(self.channel["id"], self.options.folder)
            self.progress.current = None
            self._set_state("done")
        except asyncio.CancelledError:
            self.progress.current = None
            self._set_state("stopped")
            raise
        except Exception as exc:
            error = friendly(exc)
            self.progress.error, self.progress.error_code = str(error), error.code
            self.progress.current = None
            self._set_state("failed")
        return self.progress.snapshot()

    def _check_space(self) -> None:
        """Stop before starting, not halfway, when the files can't fit."""
        free = paths.free_bytes(self.options.folder)
        if free is None or self.progress.bytes_total <= free - SPACE_RESERVE:
            return
        raise UserError(f"المساحة ما تكفي: التنزيل يحتاج {human_size(self.progress.bytes_total)}، والباقي "
                        f"{human_size(max(free - SPACE_RESERVE, 0))}. فضّي مكان أو اختر مجلد ثاني.", "disk_space")

    async def _plan(self) -> "tuple[List[Dict[str, Any]], int]":
        """New messages since the last run, plus files that failed before (and deleted ones, only if asked)."""
        newest_id = self.channel.get("lastScannedId", 0)
        by_id: Dict[int, Any] = {}
        if self.prefetched is not None:
            by_id = {m.id: m for m in self.prefetched}
        else:
            async for message in iter_files(self.client, self.entity, newest_id, self._wait, self.options.kinds):
                by_id.setdefault(message.id, message)
        newest_id = max([newest_id] + list(by_id))

        restore = self.options.restore_missing
        retry_ids = [i for i in self.library.ids_to_retry(self.channel["id"], restore) if i not in by_id]
        for batch in chunked(retry_ids, 100):
            fetched = await self._call(lambda b=batch: self.client.get_messages(self.entity, ids=b))
            for m in fetched:
                if m is not None and (getattr(m, "document", None) or getattr(m, "photo", None)):
                    by_id[m.id] = m

        plan = []
        for message in sorted(by_id.values(), key=lambda m: m.id):
            info = describe(message)
            if info["kind"] not in self.options.kinds or not self.options.filters.allows(info):
                continue
            if info["kind"] == "other" and info["ext"] in self.options.skip_exts:
                continue
            if getattr(message, "noforwards", False):  # the owner turned off saving for this post
                continue
            existing = self.library.file(self.channel["id"], message.id)
            if existing and existing["status"] in ("done", "duplicate", "rejected", "removed", "trashed"):
                still_there = existing["path"] and Path(existing["path"]).exists()
                # A file the person deleted stays deleted unless they asked for it back;
                # one they removed in the app stays removed, even then.
                if existing["status"] != "done" or still_there or not restore:
                    continue
            info["message"] = message
            plan.append(info)
        self.sections = sort_channel(self.library, self.channel["id"], [(i["name"], i["caption"]) for i in plan])
        return plan, newest_id

    async def _fetch_all(self, items: List[Dict[str, Any]], last_try: bool) -> List[Dict[str, Any]]:
        """Several files at a time. Returns the ones worth another try at the end."""
        queue = list(items)
        again: List[Dict[str, Any]] = []

        async def worker() -> None:
            while queue:
                await self._gate()
                if not queue:
                    break
                item = queue.pop(0)
                if not await self._fetch(item, last_try):
                    again.append(item)

        workers = [asyncio.ensure_future(worker()) for _ in range(max(1, min(self.options.parallel, len(queue))))]
        try:
            await asyncio.gather(*workers)
        except BaseException:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            raise
        return again

    async def _fetch(self, item: Dict[str, Any], last_try: bool) -> bool:
        """Download one file. Returns False when it should be tried again at the end."""
        message = item["message"]
        progress = self.progress
        copy = self.library.done_copy_of(item["doc_id"])
        if copy:
            self._record(item, status="duplicate", path=copy["path"], name=Path(copy["path"]).name,
                         note="نفس الملف موجود من قبل")
            progress.skipped += 1
            self._settle(item)
            self._file_event(item, "duplicate", Path(copy["path"]).name)
            return True

        topic = self.sections.of(item["name"], item["caption"])
        folder = self.options.folder
        if self.options.topic_folders:
            folder = folder / (sanitize(topic) or OTHER)
        if self.options.year_folders and item["date"]:
            folder = folder / str(item["date"].year)
        name = build_filename(item["name"], item["caption"], item["msg_id"], item["kind"], item["mime"],
                              self.options.smart_names)
        if self._adopt(item, folder / name, topic):
            return True
        folder.mkdir(parents=True, exist_ok=True)
        target = self._claim(folder, name, item["msg_id"])
        try:
            return await self._download(item, message, topic, folder, target, last_try)
        finally:
            self._claimed.discard(target)
            self._drop(item)

    def _adopt(self, item: Dict[str, Any], existing: Path, topic: str) -> bool:
        """A file with this name and exactly this size is already in the folder, and the library doesn't
        know it (the channel was removed and added again, its files kept): count it instead of saving a copy."""
        if not item["size"] or existing in self._claimed or not existing.is_file():
            return False
        if existing.stat().st_size != item["size"] or self.library.path_known(str(existing)):
            return False
        self._record(item, status="done", path=str(existing), name=existing.name, size=item["size"],
                     sha256=fingerprint(existing), topic=topic, note="كان موجود بالمجلد من قبل")
        self.progress.skipped += 1
        self._settle(item)
        self._file_event(item, "done", existing.name, str(existing))
        if self.after_file:
            self.after_file({"channel_id": self.channel["id"], "msg_id": item["msg_id"], "kind": item["kind"],
                             "path": str(existing)})
        return True

    async def _download(self, item: Dict[str, Any], message: Any, topic: str, folder: Path, target: Path,
                        last_try: bool) -> bool:
        progress = self.progress
        temp = target.with_name("." + target.name + ".part")
        attempts = 0
        refreshed = False
        while True:
            folder.mkdir(parents=True, exist_ok=True)
            self._begin(item, target.name)
            # The part file is kept through waits, network errors and quitting, so the next try continues it.
            try:
                await self._receive(message, item, temp)
                break
            except FloodWaitError as exc:
                await self._wait(exc.seconds)
            except FileReferenceExpiredError:
                if refreshed:
                    _remove(temp)
                    raise
                refreshed = True
                fresh = await self._call(lambda: self.client.get_messages(self.entity, ids=item["msg_id"]))
                message = item["message"] = fresh or message
            except asyncio.CancelledError:
                raise
            except OSError as exc:
                if exc.errno in (errno.ENOSPC, errno.EACCES, errno.EPERM, errno.EROFS):
                    _remove(temp)
                    raise
                attempts += 1
                if attempts >= len(RETRY_DELAYS):
                    _remove(temp)
                    return self._give_up(item, exc, last_try)
                await self.sleep(RETRY_DELAYS[attempts - 1])
            except Exception as exc:
                attempts += 1
                if attempts >= len(RETRY_DELAYS):
                    _remove(temp)
                    return self._give_up(item, exc, last_try)
                await self.sleep(RETRY_DELAYS[attempts - 1])

        if not temp.exists() or temp.stat().st_size == 0:
            _remove(temp)
            return self._give_up(item, UserError("الملف وصل فاضي."), last_try)
        if item["kind"] == "pdf" and not is_real_pdf(temp):
            _remove(temp)
            self._record(item, status="rejected", name=target.name, note="الملف مو PDF حقيقي، فما حفظناه")
            progress.rejected += 1
            self._settle(item)
            self._file_event(item, "rejected", target.name)
            return True

        # Same bytes already on the shelf (re-posted, or posted in another channel): keep one copy.
        sha256 = fingerprint(temp)
        twin = self.library.done_copy_by_hash(sha256)
        if twin:
            _remove(temp)
            self._record(item, status="duplicate", path=twin["path"], name=Path(twin["path"]).name, sha256=sha256,
                         note="نفس الملف موجود من قبل")
            progress.skipped += 1
            self._settle(item)
            self._file_event(item, "duplicate", Path(twin["path"]).name)
            return True

        os.replace(temp, target)
        mark_downloaded(target)
        size = target.stat().st_size
        self._record(item, status="done", path=str(target), name=target.name, size=size, sha256=sha256, topic=topic)
        progress.done += 1
        self._settle(item)
        self._file_event(item, "done", target.name, str(target))
        if self.after_file:
            self.after_file({"channel_id": self.channel["id"], "msg_id": item["msg_id"], "kind": item["kind"],
                             "path": str(target)})
        return True

    async def _receive(self, message: Any, item: Dict[str, Any], temp: Path) -> None:
        """Fetch the file into temp. A part left by a quit, a wait or a dropped connection is continued
        from where it stopped; if that doesn't work out, the file simply starts over."""
        size = item["size"]
        have = temp.stat().st_size if temp.exists() else 0
        document = getattr(message, "document", None)
        if document is not None and 0 < have < size:
            start = have - have % RESUME_STEP
            try:
                with open(temp, "r+b") as handle:
                    handle.truncate(start)
                    handle.seek(start)
                    self._on_bytes(item["msg_id"], start)
                    async for chunk in self.client.iter_download(document, offset=start, file_size=size,
                                                                 request_size=RESUME_STEP):
                        handle.write(chunk)
                        self._on_bytes(item["msg_id"], handle.tell())
                if temp.stat().st_size == size:
                    return
                log.info("continued %s came out the wrong size; starting it over", item["msg_id"])
            except (FloodWaitError, FileReferenceExpiredError, asyncio.CancelledError, asyncio.TimeoutError, OSError):
                raise  # a wait or a dropped connection: keep the part and try again
            except Exception:
                log.info("couldn't continue %s; starting it over", item["msg_id"], exc_info=True)
            _remove(temp)
            self._on_bytes(item["msg_id"], 0)
        await message.download_media(
            file=str(temp), progress_callback=lambda got, total: self._on_bytes(item["msg_id"], got)
        )

    def _give_up(self, item: Dict[str, Any], exc: BaseException, last_try: bool) -> bool:
        if not last_try:
            self._drop(item)
            return False
        error = friendly(exc)
        self._record(item, status="failed", note=str(error))
        self.progress.failed += 1
        self._settle(item)
        self._file_event(item, "failed", item["name"] or f"ملف {item['msg_id']}", note=str(error))
        return True

    async def _wait(self, seconds: int) -> None:
        previous = self.progress.state
        self.progress.wait_until = time.time() + seconds
        self._set_state("waiting")
        await self.sleep(seconds + 1)
        self.progress.wait_until = 0
        if self.progress.state == "waiting":
            self._set_state(previous if previous != "waiting" else "running")

    async def _call(self, make: Callable[[], Awaitable[Any]]) -> Any:
        while True:
            try:
                return await make()
            except FloodWaitError as exc:
                await self._wait(exc.seconds)

    # Reporting

    def _record(self, item: Dict[str, Any], **fields: Any) -> None:
        self.library.record(
            channel_id=self.channel["id"],
            msg_id=item["msg_id"],
            doc_id=item["doc_id"],
            kind=item["kind"] or "",
            mime=item["mime"],
            size=fields.pop("size", item["size"]),
            date=item["date"].isoformat() if item["date"] else "",
            caption=item["caption"],
            name=fields.pop("name", item["name"]),
            path=fields.pop("path", ""),
            **fields,
        )

    def _claim(self, folder: Path, name: str, msg_id: int) -> Path:
        """A free name in the folder that no other file of this run is being written to."""
        stem, ext = split_name(name)
        attempt, n = name, 1
        while True:
            target = unique_path(folder, attempt, msg_id)
            if target not in self._claimed:
                self._claimed.add(target)
                return target
            n += 1
            attempt = f"{stem} ({msg_id}){ext}" if n == 2 else f"{stem} ({msg_id}-{n - 1}){ext}"

    # Progress across files downloading together

    def _begin(self, item: Dict[str, Any], name: str) -> None:
        self._active[item["msg_id"]] = {"name": name, "size": item["size"], "received": 0}
        self._sync_bytes()
        self._emit_progress(force=True)

    def _on_bytes(self, msg_id: int, received: int) -> None:
        if msg_id in self._active:
            self._active[msg_id]["received"] = received
        self._sync_bytes()
        self._emit_progress()

    def _settle(self, item: Dict[str, Any]) -> None:
        """The file is finished one way or another, so all of its size counts as done."""
        self._active.pop(item["msg_id"], None)
        self._settled += item["size"]
        self._sync_bytes()

    def _drop(self, item: Dict[str, Any]) -> None:
        """Stopped without finishing (it gets another try), so its bytes no longer count."""
        if self._active.pop(item["msg_id"], None) is not None:
            self._sync_bytes()

    def _sync_bytes(self) -> None:
        active = list(self._active.values())
        self.progress.bytes_done = self._settled + sum(entry["received"] for entry in active)
        self.progress.active = active
        self.progress.current = active[-1] if active else None

    def _emit_progress(self, force: bool = False) -> None:
        now = time.monotonic()
        mark_time, mark_bytes = self._speed_mark
        if now - mark_time >= 1.0:
            instant = (self.progress.bytes_done - mark_bytes) / (now - mark_time)
            if instant >= 0:
                self.progress.speed = instant if self.progress.speed == 0 else 0.7 * self.progress.speed + 0.3 * instant
            self._speed_mark = (now, self.progress.bytes_done)
        if force or now - self._last_emit >= 0.25:
            self._last_emit = now
            self.emit("job.progress", {"channelId": self.channel["id"], **self.progress.snapshot()})

    def _file_event(self, item: Dict[str, Any], status: str, name: str, path: str = "", note: str = "") -> None:
        self.emit(
            "job.file",
            {
                "channelId": self.channel["id"],
                "file": {
                    "msgId": item["msg_id"],
                    "name": name,
                    "path": path,
                    "size": item["size"],
                    "date": item["date"].isoformat() if item["date"] else "",
                    "kind": item["kind"],
                    "status": status,
                    "note": note,
                },
            },
        )
        self._emit_progress(force=True)

    def _set_state(self, state: str) -> None:
        self.progress.state = state
        self.emit("job.progress", {"channelId": self.channel["id"], **self.progress.snapshot()})


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
