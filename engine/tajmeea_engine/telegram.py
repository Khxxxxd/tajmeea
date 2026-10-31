"""The one connection to Telegram: signing in, looking at a channel, and running downloads one at a time."""
from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import qrcode
from telethon import TelegramClient, functions, types
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from . import __version__, paths
from .errors import UserError, friendly
from .jobs import SPACE_RESERVE, DownloadJob, Filters, JobOptions, describe, iter_files
from .library import INDEX_NAME, Library
from .naming import KIND_ORDER, KINDS, sanitize
from .thumbs import COVER_KINDS, Covers
from .topics import sort_channel
from .parsing import parse_channel_link
from .vault import Vault

log = logging.getLogger("tajmeea")
Emit = Callable[[str, Dict[str, Any]], None]
ACTIVE = {"queued", "scanning", "running", "paused", "waiting"}
# Failures only the person can fix; trying again by itself at every start would just repeat them.
NEEDS_YOU = {"disk_space", "disk_full", "folder", "folder_missing", "protected"}
AUTO_SYNC_AFTER = 20 * 3600


def qr_matrix(url: str) -> List[str]:
    code = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_H)
    code.add_data(url)
    code.make(fit=True)
    return ["".join("1" if cell else "0" for cell in row) for row in code.get_matrix()]


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 6:
        return ""
    return f"+{digits[:3]}•••{digits[-2:]}"


class TelegramService:
    def __init__(self, vault: Vault, library: Library, emit: Emit, client_factory: Callable[..., Any] = TelegramClient):
        self.vault = vault
        self.library = library
        self.emit = emit
        self.factory = client_factory
        self._client: Any = None
        self._client_key: Any = None
        self._qr_task: Optional[asyncio.Task] = None
        self._phone = ""
        self._phone_hash = ""
        self._scans: Dict[int, Dict[str, Any]] = {}
        self._mine: Dict[int, Any] = {}  # channels from your own chat list, by id, for picking without a link
        self.jobs: Dict[int, DownloadJob] = {}
        self._pending: List[DownloadJob] = []
        self._current: Optional[DownloadJob] = None
        self._current_task: Optional[asyncio.Task] = None
        self._worker: Optional[asyncio.Task] = None
        self._ticker: Optional[asyncio.Task] = None
        self.covers = Covers(paths.home() / "covers", emit)

    def catch_up(self) -> None:
        """Sort every channel into its own sections (they shift as channels grow), and fill in missing covers."""
        for channel_id in self.library.channels_with_files():
            sort_channel(self.library, channel_id)
        for row in self.library.done_files(COVER_KINDS, 3000):
            self.covers.request({"channel_id": row["channel_id"], "msg_id": row["msg_id"], "kind": row["kind"],
                                 "path": row["path"]})

    # Connection

    async def client(self) -> Any:
        key = self.vault.api_key()
        if key is None:
            raise UserError("احفظ مفتاحك أول.", "no_key")
        if self._client is None or self._client_key != key:
            await self.disconnect()
            self._client = self.factory(
                StringSession(self.vault.session()),
                key.api_id,
                key.api_hash,
                device_model="Mac · تجميعة",
                system_version="macOS",
                app_version=f"Tajmeea {__version__}",
                lang_code="ar",
                system_lang_code="ar",
                flood_sleep_threshold=10,
            )
            self._client_key = key
        if not self._client.is_connected():
            try:
                await asyncio.wait_for(self._client.connect(), 25)
            except Exception as exc:
                raise friendly(exc)
        return self._client

    async def authorized_client(self) -> Any:
        client = await self.client()
        if not await client.is_user_authorized():
            raise UserError("انتهت جلستك. ادخل مرة ثانية.", "logged_out")
        return client

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self._client_key = None

    async def status(self) -> Dict[str, Any]:
        key = self.vault.api_key()
        if key is None:
            return {"hasKey": False, "authorized": False, "me": None, "offline": False}
        try:
            client = await self.client()
            authorized = await client.is_user_authorized()
            me = await self._me(client) if authorized else None
        except UserError as error:
            # Offline: trust the saved session so the library still opens.
            return {"hasKey": True, "authorized": bool(self.vault.session()), "me": None,
                    "offline": error.code == "offline", "keyMasked": key.masked()}
        if authorized:
            self.start_ticker()
        return {"hasKey": True, "authorized": authorized, "me": me, "offline": False, "keyMasked": key.masked()}

    async def _me(self, client: Any) -> Dict[str, Any]:
        user = await client.get_me()
        name = " ".join(p for p in (getattr(user, "first_name", ""), getattr(user, "last_name", "")) if p)
        return {"name": name or "حسابك", "username": getattr(user, "username", "") or "",
                "phone": mask_phone(getattr(user, "phone", ""))}

    # Signing in

    async def qr_start(self) -> Dict[str, Any]:
        client = await self.client()
        await self.qr_stop()
        self._qr_task = asyncio.ensure_future(self._qr_loop(client))
        return {"started": True}

    async def qr_stop(self) -> Dict[str, Any]:
        if self._qr_task and not self._qr_task.done():
            self._qr_task.cancel()
        self._qr_task = None
        return {"stopped": True}

    async def _qr_loop(self, client: Any) -> None:
        try:
            qr = await client.qr_login()
            while True:
                left = (qr.expires - datetime.now(timezone.utc)).total_seconds()
                self.emit("auth.qr", {"matrix": qr_matrix(qr.url), "expiresIn": max(5, int(left))})
                try:
                    await qr.wait(timeout=max(5.0, left))
                    break
                except asyncio.TimeoutError:
                    await qr.recreate()
            await self._signed_in(client)
        except asyncio.CancelledError:
            raise
        except SessionPasswordNeededError:
            self.emit("auth.password", {"hint": await self._hint(client)})
        except Exception as exc:
            error = friendly(exc)
            self.emit("auth.error", {"message": str(error), "code": error.code})

    async def phone_send(self, phone: str) -> Dict[str, Any]:
        digits = re.sub(r"\D", "", phone or "")
        if len(digits) < 8:
            raise UserError("اكتب رقمك كامل مع مفتاح الدولة، مثل ‎+965…", "phone")
        client = await self.client()
        try:
            sent = await client.send_code_request("+" + digits)
        except Exception as exc:
            raise friendly(exc)
        self._phone, self._phone_hash = "+" + digits, sent.phone_code_hash
        via_app = isinstance(getattr(sent, "type", None), types.auth.SentCodeTypeApp)
        return {"via": "app" if via_app else "sms"}

    async def phone_verify(self, code: str) -> Dict[str, Any]:
        if not self._phone_hash:
            raise UserError("اطلب الكود أول.", "phone")
        client = await self.client()
        try:
            await client.sign_in(phone=self._phone, code=re.sub(r"\D", "", code or ""), phone_code_hash=self._phone_hash)
        except SessionPasswordNeededError:
            return {"needPassword": True, "hint": await self._hint(client)}
        except Exception as exc:
            raise friendly(exc)
        return {"needPassword": False, "me": await self._signed_in(client)}

    async def password(self, password: str) -> Dict[str, Any]:
        client = await self.client()
        try:
            await client.sign_in(password=password or "")
        except Exception as exc:
            raise friendly(exc)
        return {"me": await self._signed_in(client)}

    async def _hint(self, client: Any) -> str:
        try:
            return (await client(functions.account.GetPasswordRequest())).hint or ""
        except Exception:
            return ""

    async def _signed_in(self, client: Any) -> Dict[str, Any]:
        self.vault.save_session(client.session.save())
        self._phone = self._phone_hash = ""
        me = await self._me(client)
        self.emit("auth.done", {"me": me})
        self.start_ticker()
        return me

    async def logout(self) -> Dict[str, Any]:
        await self.qr_stop()
        await self.stop_all()
        if self._client is not None:
            try:
                await self._client.log_out()
            except Exception:
                pass
        self.vault.clear_session()
        await self.disconnect()
        return {"loggedOut": True}

    async def forget_key(self) -> Dict[str, Any]:
        await self.logout()
        self.vault.clear_api_key()
        return {"forgotten": True}

    # Looking at a channel

    async def my_channels(self) -> List[Dict[str, Any]]:
        """Channels and groups you are in, so you can pick one instead of finding its link."""
        client = await self.authorized_client()
        found: List[Dict[str, Any]] = []
        try:
            async for dialog in client.iter_dialogs():
                entity = dialog.entity
                if not isinstance(entity, types.Channel):  # people, bots and old small groups
                    continue
                self._mine[entity.id] = entity
                found.append({
                    "id": entity.id,
                    "title": entity.title,
                    "username": getattr(entity, "username", "") or "",
                    "group": bool(getattr(entity, "megagroup", False)),
                    "private": not getattr(entity, "username", None),
                    "protected": bool(getattr(entity, "noforwards", False)),
                    "members": getattr(entity, "participants_count", 0) or 0,
                    "added": self.library.channel(entity.id) is not None,
                })
        except Exception as exc:
            raise friendly(exc)
        return found

    async def inspect(self, link: str = "", channelId: int = 0) -> Dict[str, Any]:
        if channelId:
            entity = self._mine.get(int(channelId))
            if entity is None:
                raise UserError("افتح ليست قنواتك مرة ثانية واختار منها.", "rescan")
            username = getattr(entity, "username", "") or ""
            client = await self.authorized_client()
        else:
            username = parse_channel_link(link)
            client = await self.authorized_client()
            try:
                entity = await client.get_entity(username)
            except ValueError:
                raise UserError("ما لقينا قناة بهالاسم. تأكد من الرابط.", "not_found")
            except Exception as exc:
                raise friendly(exc)
        if not isinstance(entity, types.Channel):
            raise UserError("هذا الرابط لحساب شخص أو بوت، مو قناة.", "not_channel")
        _refuse_protected(entity)
        try:
            full = await client(functions.channels.GetFullChannelRequest(entity))
            members = full.full_chat.participants_count or 0
            about = full.full_chat.about or ""
        except Exception:
            members, about = getattr(entity, "participants_count", 0) or 0, ""

        info = {
            "id": entity.id,
            "username": getattr(entity, "username", "") or username,
            "title": entity.title,
            "about": about,
            "members": members,
            "photo": await self._photo(client, entity),
            "accessHash": getattr(entity, "access_hash", 0) or 0,
            "group": bool(getattr(entity, "megagroup", False)),
            "private": not (getattr(entity, "username", "") or username),
        }

        tally = Tally()
        messages: List[Any] = []
        first: Optional[datetime] = None
        last: Optional[datetime] = None

        async def on_wait(seconds: int) -> None:
            self.emit("scan.wait", {"seconds": seconds})
            await asyncio.sleep(seconds + 1)

        seen = set()
        async for message in iter_files(client, entity, 0, on_wait):
            if message.id in seen:
                continue
            seen.add(message.id)
            messages.append(message)
            item = describe(message)
            if tally.add(item, message) and item["date"]:
                first = min(first, item["date"]) if first else item["date"]
                last = max(last, item["date"]) if last else item["date"]
            if len(messages) % 100 == 0:
                self.emit("scan.progress", {"documents": len(messages)})

        self._scans[entity.id] = {"entity": entity, "messages": messages, "info": info, "at": time.time()}
        info = {k: v for k, v in info.items() if k != "accessHash"}
        existing = self.library.channel(entity.id)
        return {
            "channel": info,
            **tally.result(),
            "firstDate": first.isoformat() if first else "",
            "lastDate": last.isoformat() if last else "",
            "documents": len(messages),
            "existing": existing,
            "suggestedFolder": str(paths.default_download_root() / (sanitize(info["title"]) or info["username"])),
        }

    def count(self, channelId: int, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """How many files of each kind are left once the filters apply, from the scan already in memory."""
        scan = self._scans.get(int(channelId))
        if scan is None:
            raise UserError("افحص القناة مرة ثانية.", "rescan")
        allowed = Filters.of(filters)
        tally = Tally()
        for message in scan["messages"]:
            item = describe(message)
            if allowed.allows(item):
                tally.add(item, message)
        return tally.result()

    async def _photo(self, client: Any, entity: Any) -> str:
        try:
            data = await client.download_profile_photo(entity, file=bytes, download_big=False)
        except Exception:
            return ""
        return "data:image/jpeg;base64," + base64.b64encode(data).decode() if data else ""

    # Downloads

    async def add(self, channelId: int, kinds: List[str], folder: str, yearFolders: bool = True,
                  smartNames: bool = True, autoUpdate: bool = False, topicFolders: bool = False,
                  filters: Optional[Dict[str, Any]] = None, skipExts: Optional[List[str]] = None) -> Dict[str, Any]:
        scan = self._scans.get(int(channelId))
        if scan is None:
            raise UserError("افحص القناة مرة ثانية قبل التنزيل.", "rescan")
        chosen = [k for k in kinds if k in KINDS]
        if not chosen:
            raise UserError("اختر نوع واحد على الأقل.", "kinds")
        target = _writable_folder(folder)
        options = {"folder": target, "kinds": chosen, "yearFolders": yearFolders, "smartNames": smartNames,
                   "autoUpdate": autoUpdate, "topicFolders": topicFolders, "filters": filters or {},
                   "skipExts": skipExts or []}
        self.library.save_channel(scan["info"], options)
        channel = self.library.channel(int(channelId))
        self._enqueue(channel, scan["entity"], prefetched=scan["messages"])
        self._scans.pop(int(channelId), None)
        return self.channel_summary(channel)

    async def update(self, channelId: int, restoreMissing: bool = False, recreateFolder: bool = False) -> Dict[str, Any]:
        channel = self._require_channel(channelId)
        if channel["folderState"]["state"] != "ok":
            if not recreateFolder:
                volume = channel["folderState"].get("volume")
                raise UserError(f"الهارد «{volume}» مو موصول. وصّله وجرّب مرة ثانية." if volume else
                                "ما لقينا مجلد القناة. إذا نقلته، قل لنا وين صار.", "folder_missing")
            _writable_folder(channel["folder"])
            restoreMissing = True  # the folder is new and empty: everything comes down again
        client = await self.authorized_client()
        entity = await self._find(client, channel)
        _refuse_protected(entity)
        self._enqueue(channel, entity, restore_missing=restoreMissing)
        return self.channel_summary(channel)

    async def _find(self, client: Any, channel: Dict[str, Any]) -> Any:
        """By its saved id and hash first (that works for private channels and survives a new username),
        then by username."""
        if channel["accessHash"]:
            try:
                return await client.get_entity(types.InputPeerChannel(channel["id"], channel["accessHash"]))
            except Exception:
                if not channel["username"]:
                    raise UserError("ما قدرنا نوصل للقناة. تأكد إنك للحين عضو فيها.", "not_found")
        try:
            return await client.get_entity(channel["username"])
        except Exception as exc:
            raise friendly(exc)

    async def set_filters(self, channelId: int, filters: Dict[str, Any]) -> Dict[str, Any]:
        self._require_channel(channelId)
        self.library.set_filters(int(channelId), filters or {})
        return await self.update(channelId)

    def _enqueue(self, channel: Dict[str, Any], entity: Any, prefetched: Optional[List[Any]] = None,
                 restore_missing: bool = False) -> None:
        existing = self.jobs.get(channel["id"])
        if existing and existing.progress.state in ACTIVE:
            return
        # Remembered until it finishes, so a quit or a crash doesn't leave it half done.
        self.library.set_pending(channel["id"], 2 if restore_missing else 1)
        job = DownloadJob(
            channel=channel,
            entity=entity,
            client=self._client,
            library=self.library,
            emit=self.emit,
            options=JobOptions(kinds=set(channel["kinds"]), folder=Path(channel["folder"]),
                               year_folders=channel["yearFolders"], smart_names=channel["smartNames"],
                               topic_folders=channel["topicFolders"], restore_missing=restore_missing,
                               filters=Filters.of(channel["filters"]), skip_exts=set(channel["skipExts"])),
            prefetched=prefetched,
            after_file=self.covers.request,
        )
        self.jobs[channel["id"]] = job
        self._pending.append(job)
        job._set_state("queued")
        if self._worker is None or self._worker.done():
            self._worker = asyncio.ensure_future(self._work())

    async def _work(self) -> None:
        while self._pending:
            job = self._pending.pop(0)
            self._current = job
            self._current_task = asyncio.ensure_future(job.run())
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("job crashed")
            finally:
                self._current = None
                self._current_task = None
            state, code = job.progress.state, job.progress.error_code
            if state == "done" or (state == "failed" and code in NEEDS_YOU):
                self.library.set_pending(job.channel["id"], 0)
            self.emit("channels.changed", {"channels": self.channels()})

    def pause(self, channelId: int) -> Dict[str, Any]:
        job = self.jobs.get(int(channelId))
        if job:
            job.pause()
            self.library.set_pending(int(channelId), 0)  # paused on purpose: don't restart it at next launch
        return self.job_snapshot(int(channelId))

    def resume(self, channelId: int) -> Dict[str, Any]:
        job = self.jobs.get(int(channelId))
        if job:
            job.resume()
            self.library.set_pending(int(channelId), 2 if job.options.restore_missing else 1)
        return self.job_snapshot(int(channelId))

    def cancel(self, channelId: int) -> Dict[str, Any]:
        self.library.set_pending(int(channelId), 0)
        job = self.jobs.get(int(channelId))
        if job is None:
            return {}
        if job in self._pending:
            self._pending.remove(job)
            job._set_state("stopped")
        elif job is self._current and self._current_task:
            job.resume()
            self._current_task.cancel()
        return self.job_snapshot(int(channelId))

    async def stop_all(self) -> None:
        for job in list(self._pending):
            self._pending.remove(job)
            job._set_state("stopped")
        if self._current_task:
            self._current_task.cancel()
            try:
                await self._current_task
            except (asyncio.CancelledError, Exception):
                pass

    def job_snapshot(self, channel_id: int) -> Dict[str, Any]:
        job = self.jobs.get(channel_id)
        return job.progress.snapshot() if job else {}

    # Auto updates

    def start_ticker(self) -> None:
        if self._ticker is None or self._ticker.done():
            self._ticker = asyncio.ensure_future(self._tick())

    async def _tick(self) -> None:
        await self.resume_pending()
        while True:
            await self.auto_sync()
            await asyncio.sleep(3600)

    async def resume_pending(self) -> None:
        """Downloads cut off by a quit or a crash carry on by themselves once we're signed in again."""
        for channel in self.library.channels():
            job = self.jobs.get(channel["id"])
            if not channel["pending"] or (job and job.progress.state in ACTIVE):
                continue
            try:
                await self.update(channel["id"], restoreMissing=channel["pending"] == 2)
            except UserError as error:
                log.info("couldn't resume %s: %s", channel["id"], error)
                if error.code in ("offline", "logged_out"):
                    return

    async def auto_sync(self) -> None:
        now = datetime.now(timezone.utc)
        for channel in self.library.channels():
            if not channel["autoUpdate"]:
                continue
            last = channel["lastSync"]
            if last and (now - datetime.fromisoformat(last)).total_seconds() < AUTO_SYNC_AFTER:
                continue
            try:
                await self.update(channel["id"])
            except UserError as error:
                log.info("auto update skipped for %s: %s", channel["id"], error)
                if error.code in ("offline", "logged_out"):
                    return

    # Views for the interface

    def _require_channel(self, channel_id: int) -> Dict[str, Any]:
        channel = self.library.channel(int(channel_id))
        if channel is None:
            raise UserError("ما لقينا هالقناة بمكتبتك.", "not_found")
        return channel

    def channel_summary(self, channel: Dict[str, Any]) -> Dict[str, Any]:
        return {**channel, "job": self.job_snapshot(channel["id"])}

    def channels(self) -> List[Dict[str, Any]]:
        return [self.channel_summary(c) for c in self.library.channels()]

    def with_covers(self, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for item in files:
            item["cover"] = self.covers.has(item["channelId"], item["msgId"])
        return files

    def channel_detail(self, channelId: int) -> Dict[str, Any]:
        channel = self._require_channel(channelId)
        recent = self.with_covers(self.library.recent_files(channel["id"], 40))
        # Counted after the recent files, which bring back anything put back from the Trash.
        return {**self.channel_summary(self.library.channel(channel["id"])), "recent": recent}

    def relink(self, channelId: int, folder: str) -> Dict[str, Any]:
        """The person moved the channel's folder (or renamed a drive): find the files at the new place."""
        self._require_channel(channelId)
        result = self.library.relink(int(channelId), Path(folder).expanduser())
        if result["total"] and not result["found"]:
            raise UserError("ما لقينا ملفات القناة بهالمجلد. اختر مجلد القناة نفسه.", "relink_none")
        return {**result, "channel": self.channel_summary(self.library.channel(int(channelId)))}

    def free_space(self, folder: str) -> Dict[str, Any]:
        """What a download there can use, keeping the same reserve the job keeps."""
        free = paths.free_bytes(Path(folder).expanduser()) if folder else None
        return {"free": None if free is None else max(free - SPACE_RESERVE, 0)}

    def set_auto_update(self, channelId: int, on: bool) -> Dict[str, Any]:
        self._require_channel(channelId)
        self.library.set_option(int(channelId), "auto_update", int(bool(on)))
        return self.channel_summary(self.library.channel(int(channelId)))

    def remove(self, channelId: int, trashFiles: bool = False) -> Dict[str, Any]:
        """Takes the channel out of the app. With trashFiles, also says which files the Mac app should move
        to the Trash: only this channel's own, and its index sheet."""
        channel = self.library.channel(int(channelId))
        self.cancel(channelId)
        self.jobs.pop(int(channelId), None)
        trash = None
        if trashFiles and channel:
            files, shared = self.library.files_only_here(int(channelId))
            folder = Path(channel["folder"])
            if (folder / INDEX_NAME).is_file():
                files.append(str(folder / INDEX_NAME))
            # The channel's own folder goes too once it is empty, but only when Tajmeea made it.
            own = paths.default_download_root() in folder.parents
            trash = {"paths": files, "folder": str(folder), "ownFolder": own, "shared": shared}
        self.library.remove_channel(int(channelId))
        self.covers.forget_channel(int(channelId))
        return {"removed": True, "trash": trash}


class Tally:
    """Counts a scan: files per kind, «other» files per extension, and the programs we leave out."""

    def __init__(self) -> None:
        self.kinds = {kind: {"count": 0, "bytes": 0} for kind in KIND_ORDER}
        self.others: Dict[str, Dict[str, int]] = {}
        self.blocked: Dict[str, int] = {}

    def add(self, item: Dict[str, Any], message: Any) -> bool:
        """True when the post holds a file we could save."""
        kind = item["kind"]
        if not kind or getattr(message, "noforwards", False):
            return False
        if kind == "blocked":
            self.blocked[item["ext"] or "?"] = self.blocked.get(item["ext"] or "?", 0) + 1
            return False
        self.kinds[kind]["count"] += 1
        self.kinds[kind]["bytes"] += item["size"]
        if kind == "other":
            entry = self.others.setdefault(item["ext"], {"count": 0, "bytes": 0})
            entry["count"] += 1
            entry["bytes"] += item["size"]
        return True

    def result(self) -> Dict[str, Any]:
        others = [{"ext": ext, **v} for ext, v in sorted(self.others.items(), key=lambda kv: (-kv[1]["count"], kv[0]))]
        blocked = {"count": sum(self.blocked.values()), "exts": sorted(self.blocked, key=lambda e: -self.blocked[e])[:6]}
        return {"kinds": self.kinds, "others": others, "blocked": blocked}


def _refuse_protected(entity: Any) -> None:
    """When an owner turns off saving, Telegram's own apps won't save its files, and neither do we."""
    if getattr(entity, "noforwards", False):
        raise UserError("صاحب هالقناة مانع حفظ محتواها، فتجميعة ما تنزّل منها.", "protected")


def _writable_folder(folder: str) -> Path:
    if not folder:
        raise UserError("اختر مكان الحفظ.", "folder")
    target = Path(folder).expanduser()
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".tajmeea-write-test"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        raise UserError("ما نقدر نحفظ بهالمجلد. اختر مجلد ثاني.", "folder")
    return target
