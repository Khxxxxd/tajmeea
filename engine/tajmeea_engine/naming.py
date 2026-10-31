"""What kind of file a message holds, what to call it on disk, and whether it is what it claims to be."""
from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import re
import sys
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Optional


# Each kind lists the only extensions we will ever write. Anything else gets the kind's default,
# so a channel can never drop a .command or .app into someone's folder.
KINDS = {
    "pdf": {"exts": {".pdf"}, "mimes": {"application/pdf"}, "default": ".pdf"},
    "word": {
        "exts": {".doc", ".docx", ".rtf", ".odt"},
        "mimes": {
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/rtf",
            "application/vnd.oasis.opendocument.text",
        },
        "default": ".docx",
    },
    "excel": {
        "exts": {".xls", ".xlsx", ".csv", ".ods"},
        "mimes": {
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/csv",
            "application/vnd.oasis.opendocument.spreadsheet",
        },
        "default": ".xlsx",
    },
    "slides": {
        "exts": {".ppt", ".pptx", ".odp"},
        "mimes": {
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.oasis.opendocument.presentation",
        },
        "default": ".pptx",
    },
    "books": {
        "exts": {".epub", ".mobi", ".azw3", ".djvu", ".fb2"},
        "mimes": {"application/epub+zip", "image/vnd.djvu", "application/x-mobipocket-ebook"},
        "default": ".epub",
    },
    "audio": {
        "exts": {".mp3", ".m4a", ".ogg", ".oga", ".opus", ".wav", ".flac", ".aac", ".wma", ".amr", ".aif", ".aiff", ".mka"},
        "mimes": set(),
        "default": ".mp3",
    },
    # Voice notes are told apart by Telegram, not by extension (see jobs.describe).
    "voice": {"exts": {".ogg", ".oga", ".opus"}, "mimes": set(), "default": ".ogg"},
    "archives": {
        "exts": {".zip", ".rar", ".7z"},
        "mimes": {"application/zip", "application/x-rar-compressed", "application/vnd.rar", "application/x-7z-compressed"},
        "default": ".zip",
    },
    "images": {
        "exts": {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".bmp", ".tif", ".tiff", ".svg"},
        "mimes": {"image/jpeg", "image/png", "image/webp", "image/heic", "image/gif"},
        "default": ".jpg",
    },
    "videos": {
        "exts": {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".wmv", ".flv", ".3gp", ".mpg", ".mpeg"},
        "mimes": {"video/mp4", "video/quicktime", "video/x-matroska", "video/webm"},
        "default": ".mp4",
    },
    # Any other file keeps its own extension, unless it is a program (BLOCKED_EXTS).
    "other": {"exts": set(), "mimes": set(), "default": ""},
}
KIND_ORDER = ["pdf", "word", "excel", "slides", "books", "audio", "voice", "archives", "images", "videos", "other"]

# Programs, installers, scripts and things macOS or Windows runs or installs when opened.
# «Other files» never saves these, whatever the channel posts.
BLOCKED_EXTS = {
    "app", "command", "tool", "terminal", "sh", "bash", "zsh", "csh", "ksh", "fish", "scpt", "scptd", "applescript",
    "workflow", "action", "pkg", "mpkg", "dmg", "iso", "img", "bin", "run", "appimage", "deb", "rpm",
    "exe", "msi", "msix", "appx", "bat", "cmd", "com", "scr", "pif", "cpl", "ps1", "psm1", "vbs", "vbe", "jse", "wsf",
    "wsh", "hta", "reg", "inf", "lnk", "url", "jar", "apk", "apks", "xapk", "aab", "ipa",
    "dylib", "so", "kext", "plugin", "bundle", "framework", "prefpane", "saver", "qlgenerator", "osax", "xpc",
    "mobileconfig", "webloc", "inetloc", "fileloc", "desktop", "service", "plist",
}
IMAGE_EXT_BY_MIME = {"image/png": ".png", "image/webp": ".webp", "image/heic": ".heic", "image/gif": ".gif"}
VIDEO_EXT_BY_MIME = {"video/quicktime": ".mov", "video/x-matroska": ".mkv", "video/webm": ".webm"}

AUDIO_EXT_BY_MIME = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
}


def split_name(name: str) -> "tuple[str, str]":
    """Split on the last dot only, so '6/2010 قانون.pdf' keeps everything before '.pdf'."""
    stem, dot, ext = (name or "").rpartition(".")
    if not dot or not stem or len(ext) > 10 or not ext.isalnum() or not any(c.isalpha() for c in ext):
        return name or "", ""
    return stem, "." + ext.lower()


def classify(mime: Optional[str], filename: Optional[str]) -> Optional[str]:
    mime = (mime or "").lower()
    _, ext = split_name(filename or "")
    for kind in KIND_ORDER:
        if ext and ext in KINDS[kind]["exts"]:
            return kind
    for kind in KIND_ORDER:
        if mime in KINDS[kind]["mimes"]:
            return kind
    if ext:
        # A real extension we don't know (.psd, .ai, .srt) is kept as an «other» file,
        # instead of being forced into photos or videos by a loose "image/…" label.
        return None
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("image/"):
        return "images"
    if mime.startswith("video/"):
        return "videos"
    return None


def other_extension(filename: Optional[str]) -> Optional[str]:
    """The extension an «other» file keeps ("" when it has none), or None for a program we refuse.
    The last suffix is checked as is, so a long one like .mobileconfig can't slip past the list."""
    name = (filename or "").strip().rstrip(".")
    suffix = name.rsplit(".", 1)[1].lower() if "." in name else ""
    if suffix in BLOCKED_EXTS:
        return None
    return split_name(name)[1]


def final_extension(kind: str, filename: Optional[str], mime: Optional[str]) -> str:
    _, ext = split_name(filename or "")
    if kind == "other":
        return other_extension(filename) or ""
    if ext in KINDS[kind]["exts"]:
        return ext
    if kind == "audio":
        return AUDIO_EXT_BY_MIME.get((mime or "").lower(), ".mp3")
    if kind == "images":
        return IMAGE_EXT_BY_MIME.get((mime or "").lower(), ".jpg")
    if kind == "videos":
        return VIDEO_EXT_BY_MIME.get((mime or "").lower(), ".mp4")
    return KINDS[kind]["default"]


def human_size(n: int) -> str:
    """Sizes the way the interface shows them, for messages written by the engine."""
    for unit, size in (("جيجا", 1024 ** 3), ("ميجا", 1024 ** 2)):
        if n >= size:
            return f"{n / size:.1f}".rstrip("0").rstrip(".") + f" {unit}"
    return f"{max(n, 0) // 1024} كيلو"


def fingerprint(path: Path) -> str:
    """SHA-256 of the file, so the same file under another name or message is still caught."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


_GENERIC = re.compile(
    r"^(document|documents|file|doc|untitled|new|scan(ned)?|img|image|photo|pdf|telegram|download|output|"
    r"unknown|copy|voice|audio|video|نسخة|ملف|مستند|جديد|بصمة|صوت|فيديو|صورة)?[\s_\-.]*(\d+|[\da-f]{8,}|\(\d+\))?$",
    re.I,
)
_INVISIBLE = re.compile("[​-‏‪-‮⁦-⁩﻿\u0000-\u001f\u007f]")
_URL = re.compile(r"https?://\S+|t\.me/\S+|www\.\S+", re.I)


def is_generic(stem: str) -> bool:
    s = (stem or "").strip()
    return len(s) < 3 or bool(_GENERIC.match(s))


def caption_title(caption: Optional[str], limit: int = 90) -> str:
    """The first line of the message that reads like a title."""
    for line in (caption or "").splitlines():
        line = _URL.sub(" ", line)
        line = re.sub(r"@\w+", " ", line)
        line = line.replace("#", " ").replace("_", " ")
        line = "".join(ch for ch in line if not unicodedata.category(ch).startswith(("S", "C")) or ch in "-–")
        line = re.sub(r"\s+", " ", line).strip(" -–:.،,|*")
        if sum(ch.isalpha() for ch in line) >= 3:
            if len(line) > limit:
                cut = line[:limit].rsplit(" ", 1)[0]
                line = cut if len(cut) > limit // 2 else line[:limit]
            return line
    return ""


def sanitize(stem: str, max_bytes: int = 180) -> str:
    stem = unicodedata.normalize("NFC", stem or "")
    stem = _INVISIBLE.sub("", stem)
    stem = re.sub(r"[/\\:]", "-", stem)
    stem = re.sub(r'[<>"|?*]', "", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .-_")
    encoded = stem.encode("utf-8")
    if len(encoded) > max_bytes:
        stem = encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip(" .-_")
    return stem


def build_filename(
    original: Optional[str], caption: Optional[str], msg_id: int, kind: str, mime: Optional[str], smart: bool
) -> str:
    stem, _ = split_name(original or "")
    if smart and is_generic(stem):
        stem = caption_title(caption) or stem
    stem = sanitize(stem) or f"ملف {msg_id}"
    return stem + final_extension(kind, original, mime)


def unique_path(folder: Path, filename: str, msg_id: int) -> Path:
    stem, ext = split_name(filename)
    candidate = folder / filename
    if not candidate.exists():
        return candidate
    candidate = folder / f"{stem} ({msg_id}){ext}"
    counter = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({msg_id}-{counter}){ext}"
        counter += 1
    return candidate


def is_real_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"%PDF-" in handle.read(1024)
    except OSError:
        return False


_libc = None


def mark_downloaded(path: Path) -> None:
    """Tag the file like a browser download, so macOS treats it with the same caution."""
    global _libc
    if sys.platform != "darwin":
        return
    try:
        if _libc is None:
            _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        value = f"0081;{int(time.time()):08x};Tajmeea;{uuid.uuid4()}".encode()
        _libc.setxattr(str(path).encode("utf-8"), b"com.apple.quarantine", value, len(value), 0, 0)
    except Exception:
        pass
