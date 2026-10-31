"""Stand-ins for Telegram and the Keychain, so every test runs offline and touches nothing real."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError
from telethon.errors import FileReferenceExpiredError, FloodWaitError

PDF = b"%PDF-1.7\n" + b"x" * 2000


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.items: Dict[str, str] = {}

    def get_password(self, service: str, username: str) -> Optional[str]:
        return self.items.get(f"{service}/{username}")

    def set_password(self, service: str, username: str, password: str) -> None:
        self.items[f"{service}/{username}"] = password

    def delete_password(self, service: str, username: str) -> None:
        if f"{service}/{username}" not in self.items:
            raise PasswordDeleteError("missing")
        del self.items[f"{service}/{username}"]


Keyring = MemoryKeyring


class FakeMessage:
    """A document message. `failures` is a list of exceptions raised by successive download attempts."""

    def __init__(self, msg_id: int, name: Optional[str], body: Optional[bytes] = None, mime: str = "application/pdf",
                 caption: str = "", doc_id: Optional[int] = None, year: int = 2024,
                 failures: Optional[List[BaseException]] = None, hang: bool = False, photo: bool = False,
                 music: bool = False, voice: bool = False, round_video: bool = False,
                 performer: Optional[str] = None, title: Optional[str] = None):
        body = body if body is not None else PDF + f"message {msg_id}".encode()  # every file different by default
        self.id = msg_id
        self.photo = SimpleNamespace(id=20_000 + msg_id) if photo else None
        self.sticker = None
        self.gif = None
        self.audio = SimpleNamespace() if music else None
        self.voice = SimpleNamespace() if voice else None
        self.video_note = SimpleNamespace() if round_video else None
        self.date = datetime(year, 1 + msg_id % 12, 1 + msg_id % 27, tzinfo=timezone.utc)
        self.message = caption
        self.document = None if photo else SimpleNamespace(id=doc_id if doc_id is not None else 10_000 + msg_id)
        self.file = SimpleNamespace(name=name, mime_type=mime, size=len(body), performer=performer, title=title)
        self.body = body
        self.failures = list(failures or [])
        self.hang = hang
        self.attempts = 0

    async def download_media(self, file: str, progress_callback: Any = None) -> str:
        self.attempts += 1
        half = self.body[: len(self.body) // 2]
        with open(file, "wb") as handle:
            handle.write(half)
            if progress_callback:
                progress_callback(len(half), len(self.body))
            if self.hang:
                await asyncio.sleep(3600)
            if self.failures:
                raise self.failures.pop(0)
            handle.write(self.body[len(half):])
        if progress_callback:
            progress_callback(len(self.body), len(self.body))
        return file


def flood(seconds: int) -> FloodWaitError:
    return FloodWaitError(request=None, capture=seconds)


def expired_reference() -> FileReferenceExpiredError:
    return FileReferenceExpiredError(request=None)


LISTS = {
    "InputMessagesFilterDocument": "files",
    "InputMessagesFilterPhotoVideo": "photo_video",
    "InputMessagesFilterMusic": "music",
    "InputMessagesFilterVoice": "voice",
    "InputMessagesFilterRoundVideo": "round",
}


def list_of(m: "FakeMessage") -> str:
    if m.voice:
        return "voice"
    if m.video_note:
        return "round"
    if m.audio:
        return "music"
    if m.photo or m.file.mime_type.startswith("video/"):
        return "photo_video"
    return "files"


class FakeClient:
    def __init__(self, messages: List[FakeMessage], scan_flood_once: bool = False):
        self.messages = {m.id: m for m in messages}
        self.scan_flood_once = scan_flood_once
        self.asked: List[str] = []  # which of Telegram's lists were read
        self.resumed: List[Any] = []  # (message id, offset) for every file continued part-way
        self.resume_fails = False

    def add(self, message: FakeMessage) -> None:
        self.messages[message.id] = message

    async def iter_messages(self, entity: Any, min_id: int = 0, reverse: bool = False, filter: Any = None):
        # Like Telegram: every post sits in exactly one list, and "files" leaves out photos, videos,
        # tracks, voice notes and round videos.
        filter_name = filter.__name__ if isinstance(filter, type) else type(filter).__name__
        self.asked.append(filter_name.replace("InputMessagesFilter", ""))
        wanted = LISTS[filter_name]
        ordered = sorted((m for m in self.messages.values() if m.id > min_id and list_of(m) == wanted),
                         key=lambda m: m.id)
        for index, message in enumerate(ordered):
            if self.scan_flood_once and index == 1:
                self.scan_flood_once = False
                raise flood(2)
            yield message

    async def iter_download(self, document: Any, offset: int = 0, file_size: Any = None, request_size: int = 0):
        message = next(m for m in self.messages.values() if m.document is document)
        self.resumed.append((message.id, offset))
        if self.resume_fails:
            raise ValueError("this file can't be continued")
        if message.failures:  # a network drop hits a continued download too
            raise message.failures.pop(0)
        step = request_size or 512 * 1024
        for start in range(offset, len(message.body), step):
            yield message.body[start:start + step]

    async def get_messages(self, entity: Any, ids: Any = None) -> Any:
        if isinstance(ids, list):
            return [self.messages.get(i) for i in ids]
        return self.messages.get(ids)


class RecordingSleep:
    def __init__(self) -> None:
        self.calls: List[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        await asyncio.sleep(0)


class Events:
    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []

    def __call__(self, event: str, data: Dict[str, Any]) -> None:
        self.items.append({"event": event, **data})

    def states(self) -> List[str]:
        states = []
        for item in self.items:
            if item["event"] == "job.progress" and (not states or states[-1] != item["state"]):
                states.append(item["state"])
        return states
