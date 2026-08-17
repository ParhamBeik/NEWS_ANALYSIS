"""Persian/Arabic text normalization.

Two distinct operations, deliberately not the same function:

- `clean()`  keeps text readable. Use for anything stored for display or sent to an LLM.
- `fold()`   destroys distinctions to make matching work. Use for keys, hashes, dedup.

Legacy conflated them (`normalize_text` at news_pipeline_test_version.py:323) and folded
nothing at the character level, which is why its production database contains the same
outlet under two names: 'ايسنا' with Arabic YEH (1,177 rows) and 'ایسنا' with Persian YEH
(66 rows). Any per-source matching or keyword rule silently degrades on that split.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata

ZWNJ = "‌"

# Arabic codepoints that Persian text routinely mixes in, folded to their Persian form.
_CHAR_FOLD = str.maketrans(
    {
        "ي": "ی",  # ARABIC YEH        -> FARSI YEH      ي -> ی
        "ى": "ی",  # ALEF MAKSURA      -> FARSI YEH      ى -> ی
        "ك": "ک",  # ARABIC KAF        -> KEHEH          ك -> ک
        "ة": "ه",  # TEH MARBUTA       -> HEH            ة -> ه
        "أ": "ا",  # ALEF WITH HAMZA   -> ALEF           أ -> ا
        "إ": "ا",  # ALEF WITH HAMZA   -> ALEF           إ -> ا
        "آ": "ا",  # ALEF WITH MADDA   -> ALEF           آ -> ا
        "ؤ": "و",  # WAW WITH HAMZA    -> WAW            ؤ -> و
        "ئ": "ی",  # YEH WITH HAMZA    -> FARSI YEH      ئ -> ی
        "ـ": "",        # TATWEEL (kashida), pure decoration  ـ
        ZWNJ: "",            # zero-width non-joiner: می‌رود == میرود
    }
)

# U+064B..U+0652 harakat, U+0670 superscript alef, U+06D6..U+06ED Quranic marks.
_DIACRITICS = re.compile(r"[ً-ْٰۖ-ۭ]")

_DIGIT_FOLD = str.maketrans(
    {
        **{chr(0x0660 + i): str(i) for i in range(10)},  # Arabic-Indic ٠١٢٣
        **{chr(0x06F0 + i): str(i) for i in range(10)},  # Persian    ۰۱۲۳
    }
)

_NON_WORD = re.compile(r"[^\w؀-ۿ]+")
_WHITESPACE = re.compile(r"\s+")


def fold_digits(text: str) -> str:
    """Persian and Arabic-Indic digits to ASCII. Safe on display text."""
    return (text or "").translate(_DIGIT_FOLD)


def clean(text: str) -> str:
    """Display-safe normalization: unescape HTML entities, NFC, collapse whitespace, strip.

    Preserves ZWNJ and letter identity - this text is read by humans and by the LLM,
    and mangling it changes meaning.

    Some sources' JSON-LD carries HTML-entity-encoded text (`&zwnj;`, `&laquo;`) as a
    literal string rather than the real character, which BeautifulSoup's parser does not
    unescape a second time. Left alone, `&zwnj;` sits in the title/lead/content as six
    visible characters instead of the zero-width joiner it names - visible to a reader,
    and also six extra characters `fold()` never strips, since content_hash() and title
    trigram matching both run on clean()'d text, so undecoded entities silently degraded
    dedup too, not just display.
    """
    text = html.unescape(text or "")
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\xa0", " ")
    return _WHITESPACE.sub(" ", text).strip()


def fold(text: str) -> str:
    """Matching-safe normalization. Lossy by design; never store the result for display."""
    text = unicodedata.normalize("NFC", text or "")
    text = _DIACRITICS.sub("", text)
    text = text.translate(_CHAR_FOLD).translate(_DIGIT_FOLD)
    text = text.replace("\xa0", " ").lower()
    return _WHITESPACE.sub(" ", text).strip()


def title_key(title: str) -> str:
    """Stable key for near-duplicate title matching: folded, punctuation stripped."""
    return _WHITESPACE.sub(" ", _NON_WORD.sub(" ", fold(title))).strip()


def trigrams(text: str) -> set[str]:
    """Character trigrams of a folded title, for Jaccard similarity in dedup."""
    key = title_key(text).replace(" ", "")
    return {key[i : i + 3] for i in range(len(key) - 2)} if len(key) >= 3 else {key} if key else set()


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def content_hash(title: str, lead: str, content: str) -> str:
    """Content identity. Folded so encoding variants of the same story collide."""
    raw = f"{fold(title)}|{fold(lead)}|{fold(content)[:1500]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def outlet_key(name: str) -> str:
    """Canonical key for an outlet name, so 'ايسنا' and 'ایسنا' are one outlet."""
    return title_key(name)


if __name__ == "__main__":
    # The exact collision found in the legacy production database.
    assert outlet_key("ايسنا") == outlet_key("ایسنا"), "Arabic/Persian YEH must fold"
    assert fold("ك") == "ک" and fold("١٢٣") == "123" and fold("۱۲۳") == "123"
    assert fold("می‌رود") == "میرود", "ZWNJ must not split a word for matching"
    assert clean("می‌رود") == "می‌رود", "clean() must preserve ZWNJ"
    assert clean("  a\xa0 b ") == "a b"
    assert clean("دانش&zwnj;آموز") == "دانش‌آموز", "literal HTML entities must decode"
    assert clean("&laquo;متن&raquo;") == "«متن»"
    assert jaccard(trigrams("حمله موشکی به تاسیسات"), trigrams("حمله موشكی به تاسیسات")) > 0.9
    assert content_hash("a", "b", "c") == content_hash("a", "b", "c")
    assert content_hash("a", "b", "c") != content_hash("a", "b", "d")
    print("normalize: all checks passed")
