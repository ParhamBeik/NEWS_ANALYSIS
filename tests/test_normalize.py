"""Persian/Arabic normalization.

The headline case is real: the legacy production database holds 'ايسنا' (Arabic YEH,
1,177 rows) and 'ایسنا' (Persian YEH, 66 rows) as two different outlets. They are one
outlet. Every keyword rule and dedup pass silently degraded across that split.
"""

import pytest

from news_intel.core import normalize as n


class TestCharacterFolding:
    def test_arabic_and_persian_yeh_fold_together(self):
        assert n.outlet_key("ايسنا") == n.outlet_key("ایسنا")

    @pytest.mark.parametrize(
        "arabic,persian",
        [("ي", "ی"), ("ى", "ی"), ("ك", "ک"), ("ة", "ه"), ("أ", "ا"), ("إ", "ا"), ("آ", "ا")],
    )
    def test_arabic_forms_fold_to_persian(self, arabic, persian):
        assert n.fold(arabic) == n.fold(persian)

    def test_tatweel_is_removed(self):
        assert n.fold("مـــتن") == n.fold("متن")

    def test_diacritics_are_removed(self):
        assert n.fold("مُتَن") == n.fold("متن")


class TestDigits:
    @pytest.mark.parametrize("digits", ["۱۲۳", "١٢٣", "123"])
    def test_all_digit_systems_fold_to_ascii(self, digits):
        assert n.fold(digits) == "123"

    def test_fold_digits_leaves_letters_alone(self):
        assert n.fold_digits("صفحه ۵") == "صفحه 5"


class TestCleanVersusFold:
    def test_clean_preserves_zwnj(self):
        assert n.clean("می‌رود") == "می‌رود"

    def test_clean_decodes_literal_html_entities(self):
        """khabarfoori's JSON-LD carries &zwnj;/&laquo; as literal text, not the real
        character. Undecoded, it's six visible garbage characters to a reader, and
        content_hash()/fold() - which both run on already-clean()'d text - would treat
        them as six extra characters no dedup rule ever accounts for."""
        assert n.clean("دانش&zwnj;آموز") == "دانش‌آموز"
        assert n.clean("&laquo;متن&raquo;") == "«متن»"

    def test_an_undecoded_entity_would_have_broken_dedup_too(self):
        """Same story, one copy with the raw entity, one with the real character - after
        clean() (which every source runs before constructing a RawArticle), content_hash
        must treat them as identical."""
        assert n.content_hash(n.clean("دانش&zwnj;آموز"), "", "") == n.content_hash(n.clean("دانش‌آموز"), "", "")

    def test_fold_removes_zwnj_so_spellings_match(self):
        assert n.fold("می‌رود") == n.fold("میرود")

    def test_clean_collapses_whitespace_and_nbsp(self):
        assert n.clean("  a\xa0\n b  ") == "a b"

    def test_clean_is_idempotent(self):
        text = n.clean("  متن   نمونه ")
        assert n.clean(text) == text

    @pytest.mark.parametrize("value", ["", None])
    def test_empty_input_is_safe(self, value):
        assert n.clean(value) == "" and n.fold(value) == ""


class TestSimilarity:
    def test_encoding_variants_are_near_identical(self):
        left = n.trigrams("حمله موشکی به تاسیسات")
        right = n.trigrams("حمله موشكی به تاسیسات")  # Arabic KAF
        assert n.jaccard(left, right) > 0.9

    def test_unrelated_headlines_score_low(self):
        left = n.trigrams("افزایش قیمت طلا در بازار تهران")
        right = n.trigrams("برگزاری مسابقات فوتبال جوانان")
        assert n.jaccard(left, right) < 0.2

    def test_jaccard_of_empty_sets_is_zero(self):
        assert n.jaccard(set(), set()) == 0.0
        assert n.jaccard(n.trigrams("ab"), set()) == 0.0

    def test_short_strings_do_not_crash(self):
        for text in ("", "a", "ab", "abc"):
            assert isinstance(n.trigrams(text), set)


class TestContentHash:
    def test_is_deterministic(self):
        assert n.content_hash("a", "b", "c") == n.content_hash("a", "b", "c")

    def test_differs_on_different_content(self):
        assert n.content_hash("a", "b", "c") != n.content_hash("a", "b", "d")

    def test_folds_encoding_variants_to_one_hash(self):
        """Same story, different YEH, must not become two articles."""
        assert n.content_hash("ايسنا", "", "") == n.content_hash("ایسنا", "", "")

    def test_title_key_strips_punctuation(self):
        assert n.title_key("طلا: افزایش!") == n.title_key("طلا افزایش")
