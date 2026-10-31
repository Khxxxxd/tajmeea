"""The engine process. The Mac app talks to it with one JSON object per line on stdin/stdout.

Requests:  {"id": 1, "method": "channel.inspect", "params": {"link": "t.me/x"}}
Replies:   {"id": 1, "result": {...}}  or  {"id": 1, "error": {"message": "...", "code": "..."}}
Events:    {"event": "job.progress", "data": {...}}
Nothing listens on a network port, so no website can reach it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, TextIO, Tuple

from . import __version__, paths
from .errors import UserError, friendly
from .library import Library
from .parsing import parse_api_key, scan_api_key
from .telegram import TelegramService
from .vault import Vault

log = logging.getLogger("tajmeea")
REPO = "Khxxxxd/tajmeea"
# GitHub sends this address on to the newest release's page, whose name is the version.
LATEST_RELEASE_URL = f"https://github.com/{REPO}/releases/latest"
INSTALL_URL = f"https://raw.githubusercontent.com/{REPO}/main/install.sh"


def _newer(latest: str, current: str) -> bool:
    def parts(version: str) -> Tuple[int, ...]:
        return tuple(int(p) for p in re.findall(r"\d+", version)[:3])
    return parts(latest) > parts(current)


class Engine:
    def __init__(self, write: Callable[[Dict[str, Any]], None], vault: Vault = None, library: Library = None,
                 service: TelegramService = None):
        self.write = write
        self.vault = vault or Vault()
        self.library = library or Library(paths.db_path())
        self.tg = service or TelegramService(self.vault, self.library, self.emit)
        tg = self.tg
        self.methods: Dict[str, Callable[..., Any]] = {
            "app.state": self.state,
            "key.parse": self.key_parse,
            "key.scan": scan_api_key,
            "key.save": self.key_save,
            "key.forget": tg.forget_key,
            "auth.qr.start": tg.qr_start,
            "auth.qr.stop": tg.qr_stop,
            "auth.phone.send": tg.phone_send,
            "auth.phone.verify": tg.phone_verify,
            "auth.password": tg.password,
            "auth.logout": tg.logout,
            "channel.mine": tg.my_channels,
            "channel.inspect": tg.inspect,
            "channel.count": tg.count,
            "channel.add": tg.add,
            "channel.setFilters": tg.set_filters,
            "channel.relink": tg.relink,
            "disk.free": tg.free_space,
            "channel.update": tg.update,
            "channel.get": tg.channel_detail,
            "channel.autoUpdate": tg.set_auto_update,
            "channel.remove": tg.remove,
            "job.pause": tg.pause,
            "job.resume": tg.resume,
            "job.cancel": tg.cancel,
            "library.search": self.search,
            "library.overview": self.overview,
            "library.topics": self.library.topics,
            "shelf.list": self.library.shelves,
            "shelf.create": self.shelf_create,
            "shelf.rename": self.shelf_rename,
            "shelf.delete": self.shelf_delete,
            "shelf.put": self.shelf_put,
            "shelf.files": self.shelf_files,
            "file.remove": self.file_remove,
            "file.trashed": self.file_trashed,
            "settings.get": self.settings_get,
            "settings.set": self.settings_set,
            "app.checkUpdate": self.check_update,
            "app.update": self.run_update,
        }
        self.tg.catch_up()

    def emit(self, event: str, data: Dict[str, Any]) -> None:
        self.write({"event": event, "data": data})

    async def handle(self, request: Dict[str, Any]) -> None:
        request_id = request.get("id")
        method = self.methods.get(request.get("method", ""))
        try:
            if method is None:
                raise UserError("طلب مو معروف.", "unknown_method")
            result = method(**(request.get("params") or {}))
            if asyncio.iscoroutine(result):
                result = await result
            self.write({"id": request_id, "result": result})
        except Exception as exc:
            if not isinstance(exc, UserError):
                log.exception("request %s failed", request.get("method"))
            error = friendly(exc)
            self.write({"id": request_id, "error": {"message": str(error), "code": error.code}})

    async def state(self) -> Dict[str, Any]:
        status = await self.tg.status()
        return {
            "version": __version__,
            **status,
            "channels": self.tg.channels(),
            "totals": self.library.totals(),
            "downloadRoot": str(paths.default_download_root()),
        }

    def key_parse(self, text: str) -> Dict[str, Any]:
        key = parse_api_key(text)
        return {"apiId": key.api_id, "masked": key.masked()}

    async def key_save(self, text: str) -> Dict[str, Any]:
        key = parse_api_key(text)
        if self.vault.api_key() != key:
            await self.tg.logout()
        self.vault.save_api_key(key)
        return {"masked": key.masked()}

    def search(self, query: str = "", channelId: int = None, topic: str = None) -> Dict[str, Any]:
        return {"results": self.tg.with_covers(self.library.search(query, channelId, topic))}

    # Shelves you make yourself

    def _shelf_name(self, name: str) -> str:
        name = " ".join(str(name or "").split())[:40]
        if not name:
            raise UserError("اكتب اسم للرف.", "shelf_name")
        return name

    def _require_shelf(self, shelfId: int) -> Dict[str, Any]:
        shelf = self.library.shelf(int(shelfId))
        if shelf is None:
            raise UserError("ما لقينا هالرف.", "not_found")
        return shelf

    def shelf_create(self, name: str) -> Dict[str, Any]:
        return self._require_shelf(self.library.create_shelf(self._shelf_name(name)))

    def shelf_rename(self, shelfId: int, name: str) -> Dict[str, Any]:
        self._require_shelf(shelfId)
        self.library.rename_shelf(int(shelfId), self._shelf_name(name))
        return self._require_shelf(shelfId)

    def shelf_delete(self, shelfId: int) -> Dict[str, Any]:
        self.library.delete_shelf(int(shelfId))
        return {"deleted": True}

    def shelf_put(self, shelfId: int, channelId: int, msgId: int, on: bool = True) -> Dict[str, Any]:
        self._require_shelf(shelfId)
        if self.library.file(int(channelId), int(msgId)) is None:
            raise UserError("ما لقينا الملف.", "not_found")
        self.library.put_on_shelf(int(shelfId), int(channelId), int(msgId), bool(on))
        return {"shelves": self.library.shelves()}

    def shelf_files(self, shelfId: int) -> Dict[str, Any]:
        self._require_shelf(shelfId)
        return {"results": self.tg.with_covers(self.library.shelf_files(int(shelfId)))}

    def file_remove(self, channelId: int, msgId: int) -> Dict[str, Any]:
        """Takes one file out of the library, and says which file the Mac app should move to the Trash."""
        removed = self.library.remove_file(int(channelId), int(msgId))
        if removed is None:
            raise UserError("ما لقينا الملف.", "not_found")
        path = Path(removed["path"])
        # Its own folder as the limit, so the year or section folder stays even when it's left empty:
        # Finder's «Put Back» needs somewhere to put it.
        trash = {"paths": [str(path)], "folder": str(path.parent), "ownFolder": False} if path.is_file() else None
        return {"removed": True, "trash": trash}

    def file_trashed(self, channelId: int, msgId: int, moved: bool) -> Dict[str, Any]:
        """The Mac app's answer after the Trash, so a file it couldn't move stays in the library."""
        self.library.trashed(int(channelId), int(msgId), bool(moved))
        return {"shelves": self.library.shelves()}

    SETTINGS = {"language": "ar"}

    def settings_get(self) -> Dict[str, str]:
        return {key: self.library.setting(key, default) for key, default in self.SETTINGS.items()}

    def settings_set(self, key: str, value: str) -> Dict[str, str]:
        if key not in self.SETTINGS:
            raise UserError("إعداد مو معروف.", "unknown_setting")
        self.library.set_setting(key, str(value))
        return self.settings_get()

    async def check_update(self) -> Dict[str, Any]:
        """Once a day the app asks GitHub for the newest release's number. Nothing about you is sent."""
        def fetch() -> str:
            request = urllib.request.Request(LATEST_RELEASE_URL, method="HEAD")
            with urllib.request.urlopen(request, timeout=8) as response:
                return response.geturl()
        try:
            address = await asyncio.get_running_loop().run_in_executor(None, fetch)
        except Exception:
            return {"current": __version__, "latest": None, "available": False}
        found = re.search(r"/releases/tag/v?(\d+(?:\.\d+)*)$", address)
        latest = found.group(1) if found else None
        return {"current": __version__, "latest": latest, "available": bool(latest and _newer(latest, __version__))}

    def run_update(self) -> Dict[str, Any]:
        """Runs the same one-line installer as the README; it quits the app, rebuilds it and opens it again."""
        log_file = open(paths.home() / "update.log", "ab")
        subprocess.Popen(["/bin/bash", "-c", f"curl -fsSL {INSTALL_URL} | bash"], stdout=log_file, stderr=log_file,
                         start_new_session=True)
        return {"started": True}

    def overview(self) -> Dict[str, Any]:
        return {"totals": self.library.totals(), "channels": self.tg.channels()}

    async def shutdown(self) -> None:
        await self.tg.qr_stop()
        await self.tg.stop_all()
        await self.tg.disconnect()
        self.library.close()


async def serve(stdin: TextIO, out: TextIO) -> None:
    loop = asyncio.get_running_loop()
    queue: "asyncio.Queue[str]" = asyncio.Queue()

    def read() -> None:
        for line in stdin:
            loop.call_soon_threadsafe(queue.put_nowait, line)
        loop.call_soon_threadsafe(queue.put_nowait, "")

    def write(message: Dict[str, Any]) -> None:
        out.write(json.dumps(message, ensure_ascii=False, default=str) + "\n")
        out.flush()

    threading.Thread(target=read, daemon=True).start()
    engine = Engine(write)
    write({"event": "engine.ready", "data": {"version": __version__}})
    if engine.library.recovered_from:
        write({"event": "notice", "data": {"message": "ملف المكتبة كان خربان، فسوينا واحد جديد. ملفاتك بمكانها ما انلمست."}})

    tasks = set()
    while True:
        line = await queue.get()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        task = asyncio.ensure_future(engine.handle(request))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
    if tasks:
        await asyncio.wait(set(tasks), timeout=10)
    await engine.shutdown()


def main() -> None:
    # Keep the protocol channel clean: anything a library prints goes to stderr instead.
    protocol = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)
    asyncio.run(serve(sys.stdin, protocol))


if __name__ == "__main__":
    main()
