"""Sections that fit each channel, whatever it is about.

Nothing here knows any subject. A channel's sections come from the channel itself:
1. a hashtag it puts on several posts (#تعميم، #محاضرات، #Chapter_1),
2. otherwise a word several file titles start with («قانون رقم…», «محاضرة 3…», «Lecture 5…»).
A file that fits neither goes to «أخرى», and a channel with no pattern simply has no sections.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .library import fold
from .naming import caption_title, is_generic, split_name

OTHER = "أخرى"
MIN_FILES = 3  # a word or hashtag has to repeat this often to become a section
MAX_SECTIONS = 12  # past this the sections stop helping you find anything
SIGNATURE_SHARE = 0.8  # a hashtag on almost every post is the channel's signature, not a section

_TASHKEEL = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_HASHTAG = re.compile(r"#(\w+)")
_WORD = re.compile(r"[^\W\d_]+")
# «القانون» and «قانون» are one section; single letters like و/ب are left alone so «وزارة» stays «وزارة».
_PREFIXES = ("وال", "بال", "فال", "كال", "لل", "ال")
# Words a title can start with that say nothing about what the file is.
_NOT_A_SECTION = {fold(word) for word in """
    في من على عن الى إلى مع او أو ثم رقم لسنة سنة بشأن بخصوص حول هذا هذه ذلك التي الذي جزء الجزء
    ملف نسخة جديد صورة فيديو مقطع صوت تسجيل رابط بصمة
    the a an of and or for to in on at by with from part vol volume no number file doc document copy new final
    photo image img video audio pdf
""".split()}

Word = Tuple[str, str]  # (what we compare, what we show)


def _word(text: str) -> Word:
    clean = _TASHKEEL.sub("", text)
    key = fold(clean)
    if len(key) == len(clean):
        for prefix in _PREFIXES:
            if key.startswith(prefix) and len(key) - len(prefix) >= 3:
                return key[len(prefix):], clean[len(prefix):]
    return key, clean


def title_of(name: str, caption: str) -> str:
    stem, _ = split_name(name or "")
    return caption_title(caption) if is_generic(stem) else stem


def hashtags(caption: str) -> List[Word]:
    found: List[Word] = []
    for tag in _HASHTAG.findall(_TASHKEEL.sub("", caption or "")):
        if len(tag) < 2 or tag.replace("_", "").isdigit():
            continue
        word = _word(re.sub(r"_+", " ", tag).strip())
        if word[0] and word[0] not in (k for k, _ in found):
            found.append(word)
    return found


def first_word(title: str) -> Optional[Word]:
    for text in _WORD.findall(_TASHKEEL.sub("", title or "")):
        word = _word(text)
        if len(word[0]) >= 2 and word[0] not in _NOT_A_SECTION:
            return word
    return None


class Sections:
    """Looks at all of a channel's files at once, then says which section each file belongs in."""

    def __init__(self, files: Iterable[Tuple[str, str]]):
        seen = [(hashtags(caption), first_word(title_of(name, caption))) for name, caption in files]
        shown: Dict[str, Counter] = defaultdict(Counter)
        tag_files: Counter = Counter()
        word_files: Counter = Counter()
        for tags, word in seen:
            for key, text in tags:
                tag_files[key] += 1
                shown[key][text] += 1
            if word:
                word_files[word[0]] += 1
                shown[word[0]][word[1]] += 1
        signature = SIGNATURE_SHARE * len(seen) if len(seen) >= 10 else len(seen)
        self._tags = {key for key, n in tag_files.items() if MIN_FILES <= n <= signature}
        self._words = {key for key, n in word_files.items() if n >= MIN_FILES}
        self._names = {key: max(texts.items(), key=lambda kv: (kv[1], kv[0]))[0] for key, texts in shown.items()}

        # Keep the biggest sections only, then place every file again so nobody lands in one we dropped.
        sizes = Counter(self._place(tags, word) for tags, word in seen)
        sizes.pop(None, None)
        biggest = sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_SECTIONS]
        kept = {key for key, n in biggest if n >= MIN_FILES}
        self._tags &= kept
        self._words &= kept

    def _place(self, tags: List[Word], word: Optional[Word]) -> Optional[str]:
        for key, _ in tags:
            if key in self._tags:
                return key
        if word and word[0] in self._words:
            return word[0]
        return None

    def of(self, name: str, caption: str) -> str:
        key = self._place(hashtags(caption), first_word(title_of(name, caption)))
        return self._names[key] if key else OTHER


def sort_channel(library: Any, channel_id: int, coming: Iterable[Tuple[str, str]] = ()) -> Sections:
    """Work out a channel's sections from what it already has plus what is about to download,
    and re-file what it already has, so the library never shows an old section next to a new one."""
    rows = library.files_for_sections(channel_id)
    sections = Sections([(name, caption) for _, name, caption in rows] + list(coming))
    library.set_topics(channel_id, {msg_id: sections.of(name, caption) for msg_id, name, caption in rows})
    return sections
