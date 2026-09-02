"""FROZEN INVARIANT 2/4 - the regression test this entire rebuild exists to hold.

Ported verbatim in intent from the legacy suite. If `test_unassessed_axis_must_not_veto`
ever fails, the system has re-acquired the bug that suppressed 0 of 488 security alerts.
"""

from __future__ import annotations

import pytest

from core.scoring import FLOOR, HIGH_BAR, HIGH_COUNT_REQUIRED, decide, level_score
from core.vocabulary import LEVELS, NotifyStatus

VERY_LOW, LOW, MEDIUM, HIGH, VERY_HIGH = LEVELS


class TestDecide:
    def test_two_strong_axes_with_floor_met_notifies(self):
        assert decide(HIGH, HIGH, MEDIUM).status == NotifyStatus.NOTIFY
        assert decide(VERY_HIGH, VERY_HIGH, VERY_HIGH).status == NotifyStatus.NOTIFY

    def test_floor_violation_blocks_even_with_strong_axes(self):
        assert decide(HIGH, HIGH, VERY_LOW).status == NotifyStatus.NO_NOTIFY

    def test_one_strong_axis_is_not_enough(self):
        assert decide(HIGH, MEDIUM, MEDIUM).status == NotifyStatus.NO_NOTIFY

    def test_sentinel_reproduces_the_legacy_suppression(self):
        """The bug, stated as a test: a strong security article whose gold axis was never
        assessed but got «خیلی کم» written into it anyway is silently suppressed."""
        assert decide(HIGH, VERY_LOW, HIGH).status == NotifyStatus.NO_NOTIFY

    def test_unassessed_axis_must_not_veto(self):
        """The fix. Same article, gold axis left NULL, notifies as it should."""
        assert decide(HIGH, None, HIGH).status == NotifyStatus.NOTIFY

    def test_insufficient_is_distinct_from_not_notable(self):
        outcome = decide(HIGH, None, None)
        assert outcome.status == NotifyStatus.INSUFFICIENT
        assert outcome.status != NotifyStatus.NO_NOTIFY
        assert not outcome.notify

    def test_nothing_assessed_reports_zero_axes(self):
        assert decide(None, None, None).assessed == 0

    def test_decision_carries_its_reason(self):
        assert "strong axes" in decide(HIGH, HIGH, MEDIUM).reason
        assert "floor" in decide(HIGH, HIGH, VERY_LOW).reason

    @pytest.mark.parametrize("garbage", ["", "nonsense", "very high", "HIGH"])
    def test_unrecognised_level_is_excluded_not_defaulted(self, garbage):
        """An unknown string must drop out of the vote, never score as 0 or 1 - that
        substitution is the same class of error as the sentinel."""
        assert decide(HIGH, garbage, HIGH).status == NotifyStatus.NOTIFY


class TestLevelScore:
    def test_scale_is_ordinal_and_one_based(self):
        assert [level_score(level) for level in LEVELS] == [1, 2, 3, 4, 5]

    def test_absent_and_unknown_are_none_never_a_default(self):
        assert level_score(None) is None
        assert level_score("") is None
        assert level_score("nonsense") is None


class TestThresholds:
    def test_legacy_thresholds_are_unchanged(self):
        """Pinned so a retune is a deliberate, reviewed edit rather than a drifting
        constant. Changing these changes every notify decision in the database."""
        assert (HIGH_BAR, HIGH_COUNT_REQUIRED, FLOOR) == (4, 2, 2)
