"""Where Tajmeea keeps its own data. TAJMEEA_HOME moves everything, Keychain items included."""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Dict, Optional


def home() -> Path:
    custom = os.environ.get("TAJMEEA_HOME")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / "Library" / "Application Support" / "Tajmeea"


def db_path() -> Path:
    return home() / "library.sqlite3"


def keychain_service() -> str:
    custom = os.environ.get("TAJMEEA_HOME")
    if not custom:
        return "Tajmeea"
    # A custom home gets its own Keychain namespace so two profiles never overwrite each other.
    digest = hashlib.sha1(str(Path(custom).expanduser().resolve()).encode("utf-8")).hexdigest()[:10]
    return f"Tajmeea ({digest})"


def default_download_root() -> Path:
    return Path.home() / "Downloads" / "تجميعة"


def folder_state(folder: str) -> Dict[str, str]:
    """"ok"; "volume" when it lives on a drive that isn't plugged in; "missing" when it was moved,
    renamed or deleted. Only "ok" lets us judge files one by one."""
    path = Path(folder)
    if path.is_dir():
        return {"state": "ok"}
    parts = path.parts
    if len(parts) > 2 and parts[1] == "Volumes" and not Path("/Volumes", parts[2]).exists():
        return {"state": "volume", "volume": parts[2]}
    return {"state": "missing"}


def free_bytes(folder: Path) -> Optional[int]:
    """Free space on the drive the folder is (or will be) on."""
    path = Path(folder)
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None
