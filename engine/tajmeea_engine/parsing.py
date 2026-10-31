"""Turning what people paste into something we can use: their key, or a channel link."""
from __future__ import annotations

import re
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from .errors import UserError
from .vault import ApiKey

_LABELED_ID = re.compile(r"api[\s_-]*id\D{0,24}?(\d{4,10})(?!\d)", re.I)
# The 2026 my.telegram.org page puts a "secret" tag between the label and the value.
_LABELED_HASH = re.compile(r"api[\s_-]*hash[\s\S]{0,60}?(?<![0-9a-f])([0-9a-f]{32})(?![0-9a-f])", re.I)
_BARE_HASH = re.compile(r"(?<![0-9a-f])([0-9a-f]{32})(?![0-9a-f])", re.I)
_BARE_ID = re.compile(r"(?<![\d+.:])(\d{5,10})(?![\d.:])")
# …and shows the hash as dots until you reveal it, so copying the page copies dots.
_HIDDEN_HASH = re.compile(r"api[\s_-]*hash[\s\S]{0,60}?[•●*]{6,}", re.I)

KEY_NOT_FOUND = "ما لقينا المفتاح بالنص. تأكد إنك نسخت صفحة المفتاح كاملة."
HASH_HIDDEN = (
    "لقينا رقم التطبيق، بس الـ api_hash مخفي بالصفحة وطالع نقاط. "
    "ارجع لموقع تيليجرام، واضغط على النقاط عشان يبين، أو انسخه بزر النسخ اللي جنبه، وارجع هني."
)


def scan_api_key(text: str) -> Dict[str, Any]:
    """Whatever part of the key is in the text: the whole page, or one value copied with the page's copy button."""
    text = text or ""
    id_match = _LABELED_ID.search(text)
    hash_match = _LABELED_HASH.search(text)
    api_id = id_match.group(1) if id_match else None
    api_hash = hash_match.group(1).lower() if hash_match else None

    if api_hash is None:
        hashes = {h.lower() for h in _BARE_HASH.findall(text)}
        if len(hashes) == 1:
            api_hash = hashes.pop()
    if api_id is None:
        # Only guess when there is exactly one plausible number once the hash is removed.
        without_hashes = _BARE_HASH.sub(" ", text)
        ids = set(_BARE_ID.findall(without_hashes))
        if len(ids) == 1:
            api_id = ids.pop()
    return {
        "apiId": int(api_id) if api_id else None,
        "apiHash": api_hash,
        "hashHidden": bool(not api_hash and _HIDDEN_HASH.search(text)),
    }


def parse_api_key(text: str) -> ApiKey:
    found = scan_api_key(text)
    if found["apiId"] and found["hashHidden"]:
        raise UserError(HASH_HIDDEN, "hash_hidden")
    if not found["apiId"] or not found["apiHash"]:
        raise UserError(KEY_NOT_FOUND, "key_not_found")
    return ApiKey(found["apiId"], found["apiHash"])


_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
_HOSTS = {"t.me", "www.t.me", "telegram.me", "www.telegram.me", "telegram.dog"}
PRIVATE = "هذا رابط قناة خاصة. تجميعة تشتغل مع القنوات العامة بس."
BAD_NAME = "اسم القناة مو صحيح. انسخ الرابط من تيليجرام مرة ثانية."


def parse_channel_link(raw: str) -> str:
    """Accepts @name, name, t.me/name, a post link, /s/ preview links and tg:// links. Returns the username."""
    text = (raw or "").strip().strip("<>\"'")
    if not text:
        raise UserError("الصق رابط القناة أو اسمها.", "empty")

    if text.lower().startswith("tg://"):
        domain = parse_qs(urlparse(text).query).get("domain", [""])[0]
        return _username(domain)
    if text.startswith("@"):
        return _username(text[1:])
    if "/" not in text and "." not in text:
        return _username(text)

    parsed = urlparse(text if "://" in text else "https://" + text)
    host = (parsed.hostname or "").lower()
    if host not in _HOSTS:
        raise UserError("هذا مو رابط تيليجرام. الرابط الصحيح يبدأ بـ t.me", "not_telegram")
    parts = [p for p in parsed.path.split("/") if p]
    if parts[:1] == ["s"]:
        parts = parts[1:]
    if not parts:
        raise UserError(BAD_NAME, "bad_name")
    first = parts[0]
    if first.startswith("+") or first.lower() in {"joinchat", "c"}:
        raise UserError(PRIVATE, "private")
    return _username(first)


def _username(name: str) -> str:
    name = (name or "").strip().lstrip("@")
    if not _USERNAME.match(name):
        raise UserError(BAD_NAME, "bad_name")
    return name
