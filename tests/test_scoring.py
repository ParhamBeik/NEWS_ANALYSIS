"""Notification rule, including a regression test for the legacy suppression bug.

Values below are transcribed from real rows in the legacy databases rather than read from
them at test time, so the suite stays offline and portable.
"""

import pytest

from news_intel.core.scoring import (
    INSUFFICIENT,
    NO_NOTIFY,
    NOTIFY,
    decide,
)

VERY_LOW, LOW, MID, HIGH, VERY_HIGH = "خیلی کم", "کم", "متوسط", "زیاد", "خیلی زیاد"


class TestBaselineRule:
    """Legacy thresholds preserved, so the rebuild is comparable before Phase 4.4 retunes."""

    def test_two_strong_axes_with_floor_met_notifies(self):
        assert decide(HIGH, HIGH, MID).status == NOTIFY

    def test_all_maximum_notifies(self):
        assert decide(VERY_HIGH, VERY_HIGH, VERY_HIGH).status == NOTIFY

    def test_one_strong_axis_is_not_enough(self):
        assert decide(HIGH, MID, MID).status == NO_NOTIFY

    def test_floor_violation_blocks_despite_two_strong_axes(self):
        assert decide(VERY_HIGH, VERY_HIGH, VERY_LOW).status == NO_NOTIFY

    def test_mid_everywhere_does_not_notify(self):
        assert decide(MID, MID, MID).status == NO_NOTIFY


class TestLegacySuppressionRegression:
    """news_pipeline_test_version.py:2230-2237.

    The category-specific prompts stopped asking security articles about gold impact, and
    the code substituted a hardcoded "خیلی کم" (score 1). The rule requires every assessed
    axis to be >= 2, so that sentinel made the floor unreachable and silently suppressed
    every security and economics notification: 0 of 488 security articles alerted in the
    test pipeline, against 50.2% in production.
    """

    def test_sentinel_reproduces_the_suppression(self):
        # A strong security article, gold axis filled with the legacy sentinel.
        assert decide(HIGH, VERY_LOW, VERY_HIGH).status == NO_NOTIFY

    def test_unassessed_axis_must_not_veto(self):
        # Same article, gold axis correctly marked unassessed.
        assert decide(HIGH, None, VERY_HIGH).status == NOTIFY

    def test_every_strong_security_article_was_suppressed(self):
        """Sweep the security-shaped space: sentinel suppresses all of it."""
        for confidence in (HIGH, VERY_HIGH):
            for relevance in (HIGH, VERY_HIGH):
                assert decide(confidence, VERY_LOW, relevance).status == NO_NOTIFY
                assert decide(confidence, None, relevance).status == NOTIFY

    def test_economics_shape_is_the_mirror_image(self):
        # Economics prompt omitted security_relevance and substituted the same sentinel.
        assert decide(HIGH, VERY_HIGH, VERY_LOW).status == NO_NOTIFY
        assert decide(HIGH, VERY_HIGH, None).status == NOTIFY


class TestUnassessedAxes:
    def test_two_assessed_axes_are_enough_to_decide(self):
        result = decide(HIGH, None, HIGH)
        assert result.status == NOTIFY
        assert result.assessed == 2

    def test_one_assessed_axis_is_insufficient(self):
        result = decide(HIGH, None, None)
        assert result.status == INSUFFICIENT
        assert result.assessed == 1

    def test_no_assessment_is_insufficient_not_negative(self):
        """INSUFFICIENT must stay distinct from NO_NOTIFY, or a broken evaluation
        step looks exactly like a quiet news day."""
        result = decide(None, None, None)
        assert result.status == INSUFFICIENT
        assert result.status != NO_NOTIFY

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
