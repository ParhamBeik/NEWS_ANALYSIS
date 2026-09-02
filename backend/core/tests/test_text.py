"""Persian normalization. Underpins dedup (invariant 1/4) and content identity.

The Arabic/Persian folding is not cosmetic: the legacy database holds one outlet under two
spellings - 'ايسنا' with Arabic YEH (1,177 rows) and 'ایسنا' with Persian YEH (66 rows) -
because matching ran on unfolded text.
"""

from __future__ import annotations

import pytest

from core.text import (
    clean,
    content_hash,
    fold,
    jaccard,
    parse_iso,
    title_key,
    trigrams,
)


class TestFold:
    def test_arabic_and_persian_yeh_fold_together(self):
        assert title_key("ايسنا") == title_key("ایسنا")

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("ك", "ک"), ("١٢٣", "123"), ("۱۲۳", "123"), ("ة", "ه"), ("آ", "ا")],
    )
    def test_character_and_digit_folding(self, raw, expected):
        assert fold(raw) == expected

    def test_zwnj_must_not_split_a_word_for_matching(self):
        assert fold("می‌رود") == "میرود"

    def test_none_and_empty_are_safe(self):
        assert fold(None) == "" and fold("") == ""


class TestClean:
    def test_clean_preserves_zwnj_because_it_is_display_text(self):
        """fold() destroys the ZWNJ, clean() must not - they are different jobs and
        conflating them is what produced the duplicate-outlet bug."""
        assert clean("می‌رود") == "می‌رود"

    def test_collapses_whitespace_including_nbsp(self):
        assert clean("  a\xa0 b ") == "a b"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("دانش&zwnj;آموز", "دانش‌آموز"), ("&laquo;متن&raquo;", "«متن»")],
    )
    def test_literal_html_entities_are_decoded(self, raw, expected):
        """Some sources' JSON-LD carries entity text BeautifulSoup does not unescape a
        second time; left alone it is visible junk that also degrades hashing."""
        assert clean(raw) == expected

    def test_none_is_safe(self):
        assert clean(None) == ""


class TestSimilarity:
    def test_arabic_kaf_variant_still_matches_the_same_headline(self):
        left = trigrams("حمله موشکی به تاسیسات")
        right = trigrams("حمله موشكی به تاسیسات")
        assert jaccard(left, right) > 0.9

    def test_jaccard_of_empty_sets_is_zero_not_an_error(self):
        assert jaccard(set(), set()) == 0.0
        assert jaccard(trigrams("abc"), set()) == 0.0

    def test_short_titles_still_produce_a_key(self):
        assert trigrams("ab") == {"ab"}
        assert trigrams("") == set()


class TestContentHash:
    def test_is_stable_and_discriminating(self):
        assert content_hash("a", "b", "c") == content_hash("a", "b", "c")
        assert content_hash("a", "b", "c") != content_hash("a", "b", "d")

    def test_encoding_variants_of_the_same_story_collide(self):
        assert content_hash("ايسنا", "", "") == content_hash("ایسنا", "", "")


class TestParseIso:
    def test_tolerates_trailing_z(self):
        assert parse_iso("2026-01-01T00:00:00Z") is not None

    @pytest.mark.parametrize("bad", [None, "", "nope", "2026-13-45"])
    def test_invalid_input_is_none_not_an_exception(self, bad):
        assert parse_iso(bad) is None
