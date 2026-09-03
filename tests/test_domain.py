"""Pure domain logic: Persian text normalization, the notify rule, prompt/schema coherence.

The normalization headline case is real: the legacy production database holds 'ايسنا'
(Arabic YEH, 1,177 rows) and 'ایسنا' (Persian YEH, 66 rows) as two different outlets. They
are one outlet, and every keyword rule and dedup pass silently degraded across that split.
"""

import pytest
from pydantic import ValidationError

from news_intel import prompts, text
from news_intel.prompts import GOLD_TRENDS, EvaluationOutput
from news_intel.scoring import INSUFFICIENT, LEVELS, NO_NOTIFY, NOTIFY, decide
from news_intel.sources import RawArticle

VERY_LOW, LOW, MID, HIGH, VERY_HIGH = LEVELS
ARTICLE = RawArticle(source="test", url="https://test/1", title="خبر")


# ----------------------------------------------------------------------- text folding


class TestFolding:
    def test_arabic_and_persian_yeh_fold_together(self):
        assert text.title_key("ايسنا") == text.title_key("ایسنا")

    @pytest.mark.parametrize("arabic,persian", [
        ("ي", "ی"), ("ى", "ی"), ("ك", "ک"), ("ة", "ه"), ("أ", "ا"), ("إ", "ا"), ("آ", "ا"),
    ])
    def test_arabic_forms_fold_to_persian(self, arabic, persian):
        assert text.fold(arabic) == text.fold(persian)

    def test_tatweel_and_diacritics_are_removed(self):
        assert text.fold("مـــتن") == text.fold("مُتَن") == text.fold("متن")

    @pytest.mark.parametrize("digits", ["۱۲۳", "١٢٣", "123"])
    def test_all_digit_systems_fold_to_ascii(self, digits):
        assert text.fold(digits) == "123"


class TestCleanVersusFold:
    def test_clean_preserves_zwnj_and_fold_removes_it(self):
        assert text.clean("می‌رود") == "می‌رود"
        assert text.fold("می‌رود") == text.fold("میرود")

    def test_clean_decodes_literal_html_entities(self):
        """khabarfoori's JSON-LD carries &zwnj;/&laquo; as literal text, not the real
        character. Undecoded that is six visible garbage characters to a reader, and
        content_hash()/fold() - which both run on already-clean()'d text - would treat
        them as six extra characters no dedup rule ever accounts for."""
        assert text.clean("دانش&zwnj;آموز") == "دانش‌آموز"
        assert text.clean("&laquo;متن&raquo;") == "«متن»"
        assert text.content_hash(text.clean("دانش&zwnj;آموز"), "", "") == \
            text.content_hash(text.clean("دانش‌آموز"), "", "")

    def test_clean_collapses_whitespace_and_is_idempotent(self):
        once = text.clean("  a\xa0\n b  ")
        assert once == "a b" and text.clean(once) == once

    @pytest.mark.parametrize("value", ["", None])
    def test_empty_input_is_safe(self, value):
        assert text.clean(value) == "" and text.fold(value) == ""


class TestSimilarityAndHashing:
    def test_encoding_variants_are_near_identical(self):
        left, right = text.trigrams("حمله موشکی به تاسیسات"), text.trigrams("حمله موشكی به تاسیسات")
        assert text.jaccard(left, right) > 0.9

    def test_unrelated_headlines_score_low(self):
        left = text.trigrams("افزایش قیمت طلا در بازار تهران")
        right = text.trigrams("برگزاری مسابقات فوتبال جوانان")
        assert text.jaccard(left, right) < 0.2

    def test_jaccard_of_empty_sets_is_zero(self):
        assert text.jaccard(set(), set()) == 0.0
        assert text.jaccard(text.trigrams("ab"), set()) == 0.0

    @pytest.mark.parametrize("value", ["", "a", "ab", "abc"])
    def test_short_strings_do_not_crash(self, value):
        assert isinstance(text.trigrams(value), set)

    def test_content_hash_is_deterministic_and_content_sensitive(self):
        assert text.content_hash("a", "b", "c") == text.content_hash("a", "b", "c")
        assert text.content_hash("a", "b", "c") != text.content_hash("a", "b", "d")

    def test_content_hash_folds_encoding_variants_to_one_hash(self):
        """Same story, different YEH, must not become two articles."""
        assert text.content_hash("ايسنا", "", "") == text.content_hash("ایسنا", "", "")

    def test_title_key_strips_punctuation(self):
        assert text.title_key("طلا: افزایش!") == text.title_key("طلا افزایش")

    def test_parse_iso_tolerates_z_and_rejects_junk(self):
        assert text.parse_iso("2026-01-01T00:00:00Z") is not None
        assert text.parse_iso("پنجشنبه") is None and text.parse_iso(None) is None


# ---------------------------------------------------------------------- notify rule


class TestBaselineRule:
    """Legacy thresholds preserved, so the rebuild stays comparable before it is retuned."""

    @pytest.mark.parametrize("axes,expected", [
        ((HIGH, HIGH, MID), NOTIFY),
        ((VERY_HIGH, VERY_HIGH, VERY_HIGH), NOTIFY),
        ((HIGH, MID, MID), NO_NOTIFY),                     # one strong axis is not enough
        ((VERY_HIGH, VERY_HIGH, VERY_LOW), NO_NOTIFY),     # floor violation blocks
        ((MID, MID, MID), NO_NOTIFY),
    ])
    def test_thresholds(self, axes, expected):
        assert decide(*axes).status == expected


class TestLegacySuppressionRegression:
    """news_pipeline_test_version.py:2230-2237.

    The category-specific prompts stopped asking security articles about gold impact, and
    the code substituted a hardcoded "خیلی کم" (score 1). The rule requires every assessed
    axis to be >= 2, so that sentinel made the floor unreachable and silently suppressed
    every security and economics notification: 0 of 488 security articles alerted in the
    test pipeline, against 50.2% in production.
    """

    def test_every_strong_security_article_was_suppressed(self):
        for confidence in (HIGH, VERY_HIGH):
            for relevance in (HIGH, VERY_HIGH):
                assert decide(confidence, VERY_LOW, relevance).status == NO_NOTIFY
                assert decide(confidence, None, relevance).status == NOTIFY

    def test_economics_shape_is_the_mirror_image(self):
        assert decide(HIGH, VERY_HIGH, VERY_LOW).status == NO_NOTIFY
        assert decide(HIGH, VERY_HIGH, None).status == NOTIFY


class TestUnassessedAxes:
    def test_two_assessed_axes_are_enough_to_decide(self):
        result = decide(HIGH, None, HIGH)
        assert result.status == NOTIFY and result.assessed == 2

    def test_one_assessed_axis_is_insufficient(self):
        result = decide(HIGH, None, None)
        assert result.status == INSUFFICIENT and result.assessed == 1

    def test_no_assessment_is_insufficient_not_negative(self):
        """INSUFFICIENT must stay distinct from NO_NOTIFY, or a broken evaluation step
        looks exactly like a quiet news day."""
        assert decide(None, None, None).status == INSUFFICIENT != NO_NOTIFY

    def test_unrecognised_level_is_treated_as_unassessed(self):
        assert decide(HIGH, "نامشخص", HIGH).status == NOTIFY
        assert decide(HIGH, "", HIGH).assessed == 2

    @pytest.mark.parametrize("junk", ["", None, "unknown", "متوسط ", "HIGH"])
    def test_junk_never_counts_as_a_score(self, junk):
        assert decide(junk, junk, junk).status == INSUFFICIENT


class TestDecisionMetadata:
    def test_reason_is_populated_for_the_audit_trail(self):
        assert decide(HIGH, HIGH, MID).reason
        assert "floor" in decide(HIGH, HIGH, VERY_LOW).reason

    def test_notify_property_matches_status(self):
        assert decide(HIGH, HIGH, MID).notify is True
        assert decide(MID, MID, MID).notify is False
        assert decide(None, None, None).notify is False


# --------------------------------------------------------- prompt / schema coherence


class TestSchema:
    def test_evaluation_requires_two_actual_axes(self):
        with pytest.raises(ValidationError):
            EvaluationOutput(confidence_occurrence="زیاد", rationale="one axis only")

    @pytest.mark.parametrize("trend", GOLD_TRENDS)
    def test_every_gold_trend_value_validates(self, trend):
        assert EvaluationOutput(confidence_occurrence="زیاد", gold_price_impact="کم",
                                gold_trend=trend, rationale="ok").gold_trend == trend

    def test_a_retired_trend_value_is_rejected(self):
        with pytest.raises(ValidationError):
            EvaluationOutput(confidence_occurrence="زیاد", gold_price_impact="کم",
                             gold_trend="→", rationale="ok")


class TestPolicyMatchesSchema:
    """Policy text, schema, and workbook vocabulary have to move together - they drifted
    once already, shipping «→» and «?» while the workbook's dropdown accepted neither."""

    def test_the_evaluation_policy_names_every_level_the_schema_accepts(self):
        policy = prompts.load_policy("evaluation")
        assert not [level for level in LEVELS if level not in policy]

    def test_the_evaluation_policy_names_exactly_the_trends_the_schema_accepts(self):
        policy = prompts.load_policy("evaluation")
        assert all(trend in policy for trend in GOLD_TRENDS)
        # "?" is ordinary punctuation in prose, so only the unambiguous symbol is checked.
        assert "→" not in policy

    def test_the_classification_policy_names_every_category(self):
        policy = prompts.load_policy("classification")
        assert all(c in policy for c in ("security", "economics", "security/economics", "other"))

    def test_the_policies_state_that_an_unassessed_axis_is_null(self):
        """The one instruction that prevents the legacy suppression bug from returning."""
        policy = prompts.load_policy("evaluation")
        assert "null" in policy and "خیلی کم" in policy


class TestPromptAssembly:
    def test_policy_stays_separate_from_article_data(self):
        messages = prompts.messages("classification", ARTICLE, [])
        assert messages[0]["role"] == "system" and "main meaning" in messages[0]["content"]
        assert "reviewed_examples" in messages[1]["content"]

    def test_the_shipped_policies_are_the_ones_that_get_sent(self):
        """Guards against the fallback defaults silently standing in for the real files."""
        system = prompts.messages("evaluation", ARTICLE, [], category="security")[0]["content"]
        assert system == prompts.load_policy("evaluation")
        assert len(system) > len(prompts._DEFAULTS["evaluation"])

    def test_each_task_sends_its_own_policy(self):
        assert prompts.messages("classification", ARTICLE, [])[0]["content"] != \
            prompts.messages("summary", ARTICLE, [])[0]["content"]

    def test_article_text_is_truncated_before_it_reaches_the_provider(self):
        long = RawArticle(source="test", url="https://test/1", title="خبر", content="ب" * 20_000)
        assert len(prompts.messages("summary", long, [])[1]["content"]) < 12_000

    def test_editing_a_policy_changes_the_prompt_version(self, tmp_path, monkeypatch):
        """Version is a content hash, so a prompt edit is never silently untracked."""
        monkeypatch.setattr(prompts.config, "PROMPTS_DIR", tmp_path)
        for name in ("classification", "evaluation", "summary"):
            (tmp_path / f"{name}.md").write_text("original", encoding="utf-8")
        before = prompts.prompt_version()

        (tmp_path / "evaluation.md").write_text("original, plus one clarification", encoding="utf-8")
        assert prompts.prompt_version() != before
