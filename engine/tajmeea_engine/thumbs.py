"""Covers for the shelf: the same small previews Finder shows, made once by macOS Quick Look and kept."""
from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("tajmeea")
COVER_KINDS = {"pdf", "word", "excel", "slides", "books", "images", "videos"}
QLMANAGE = "/usr/bin/qlmanage"


class Covers:
    def __init__(self, root: Path, emit: Callable[[str, Dict[str, Any]], None]):
        self.root = root
        self.emit = emit
        self._queue: Optional[asyncio.Queue] = None
        self._worker: Optional[asyncio.Task] = None
        self.available = sys.platform == "darwin" and Path(QLMANAGE).exists()

    def path(self, channel_id: int, msg_id: int) -> Path:
        return self.root / str(channel_id) / f"{msg_id}.png"

    def has(self, channel_id: int, msg_id: int) -> bool:
        return self.path(channel_id, msg_id).exists()

    def request(self, item: Dict[str, Any]) -> None:
        """Queue a cover for a finished file; cheap to call, the work happens in the background."""
        if not self.available or item.get("kind") not in COVER_KINDS or self.has(item["channel_id"], item["msg_id"]):
            return
        if self._queue is None:
            self._queue = asyncio.Queue()
        self._queue.put_nowait(item)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.ensure_future(self._work())

    async def _work(self) -> None:
        while self._queue and not self._queue.empty():
            item = self._queue.get_nowait()
            try:
                if await self._make(item):
                    self.emit("file.cover", {"channelId": item["channel_id"], "msgId": item["msg_id"]})
            except Exception:
                log.exception("cover failed for %s", item.get("path"))

    async def _make(self, item: Dict[str, Any]) -> bool:
        source = Path(item["path"])
        target = self.path(item["channel_id"], item["msg_id"])
        if not source.exists() or target.exists():
            return False
        with tempfile.TemporaryDirectory() as tmp:
            process = await asyncio.create_subprocess_exec(
                QLMANAGE, "-t", "-s", "320", "-o", tmp, str(source),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(process.wait(), 20)
            except asyncio.TimeoutError:
                process.kill()
                return False
            made = Path(tmp) / f"{source.name}.png"
            if not made.exists():
                return False
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(made), str(target))
        return True

    def forget_channel(self, channel_id: int) -> None:
        shutil.rmtree(self.root / str(channel_id), ignore_errors=True)
