"""Persian text normalization and date parsing.

Two normalizations, deliberately not the same function:

- `clean()` keeps text readable. Use for anything stored for display or sent to an LLM.
- `fold()` destroys distinctions so matching works. Use for keys, hashes, dedup.

Conflating them is why the legacy database holds one outlet under two spellings - 'ايسنا'
with Arabic YEH (1,177 rows) and 'ایسنا' with Persian YEH (66 rows).

The character tables below are transcribed rather than rederived: they encode which Arabic
codepoints Persian news sources actually mix in, measured against the corpus.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import datetime

import jdatetime

ZWNJ = "‌"

# Arabic codepoints Persian text routinely mixes in, folded to their Persian form.
_CHAR_FOLD = str.maketrans({
    "ي": "ی", "ى": "ی", "ئ": "ی",   # ARABIC YEH / ALEF MAKSURA / YEH+HAMZA -> FARSI YEH
    "ك": "ک",                        # ARABIC KAF -> KEHEH
    "ة": "ه",                        # TEH MARBUTA -> HEH
    "أ": "ا", "إ": "ا", "آ": "ا",   # ALEF variants -> ALEF
    "ؤ": "و",                        # WAW WITH HAMZA -> WAW
    "ـ": "", ZWNJ: "",               # kashida decoration; ZWNJ (می‌رود == میرود)
})
_DIGIT_FOLD = str.maketrans({
    **{chr(0x0660 + i): str(i) for i in range(10)},  # Arabic-Indic ٠١٢٣
    **{chr(0x06F0 + i): str(i) for i in range(10)},  # Persian    ۰۱۲۳
})
_DIACRITICS = re.compile(r"[ً-ْٰۖ-ۭ]")
_NON_WORD = re.compile(r"[^\w؀-ۿ]+")
_WHITESPACE = re.compile(r"\s+")


def clean(text: str | None) -> str:
    """Display-safe: unescape entities, NFC, collapse whitespace. Preserves ZWNJ.

    Some sources' JSON-LD carries literal `&zwnj;`/`&laquo;` strings that BeautifulSoup
    does not unescape a second time; left alone they are visible junk that also degrades
    hashing and trigram matching, both of which run on cleaned text.
    """
    text = unicodedata.normalize("NFC", html.unescape(text or "")).replace("\xa0", " ")
    return _WHITESPACE.sub(" ", text).strip()


def fold(text: str | None) -> str:
    """Matching-safe. Lossy by design; never store the result for display."""
    text = _DIACRITICS.sub("", unicodedata.normalize("NFC", text or ""))
    text = text.translate(_CHAR_FOLD).translate(_DIGIT_FOLD).replace("\xa0", " ").lower()
    return _WHITESPACE.sub(" ", text).strip()


def title_key(title: str | None) -> str:
    """Folded, punctuation-stripped key for near-duplicate title matching."""
    return _WHITESPACE.sub(" ", _NON_WORD.sub(" ", fold(title))).strip()


def trigrams(text: str | None) -> set[str]:
    """Character trigrams of a folded title, for Jaccard similarity in dedup."""
    key = title_key(text).replace(" ", "")
    if len(key) >= 3:
        return {key[i : i + 3] for i in range(len(key) - 2)}
    return {key} if key else set()


def jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left and right else 0.0


def content_hash(title: str | None, lead: str | None, content: str | None) -> str:
    """Content identity, folded so encoding variants of the same story collide."""
    raw = f"{fold(title)}|{fold(lead)}|{fold(content)[:1500]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def parse_iso(value: str | None) -> datetime | None:
    """ISO-8601 timestamp tolerating a trailing 'Z'. None on empty/invalid input."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def jalali_str(value: jdatetime.date) -> str:
    return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"


def to_jalali(moment: datetime) -> jdatetime.date:
    """Gregorian datetime (already in the target timezone) -> Jalali date."""
    return jdatetime.date.fromgregorian(
        year=moment.year, month=moment.month, day=moment.day
    )
