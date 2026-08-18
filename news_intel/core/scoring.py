"""The notification decision.

Ported from legacy `calculate_notification_status` (news_pipeline_test_version.py:919)
with one semantic change: axes that were never assessed are absent, not zero.

Why that change exists. Legacy's category-specific prompts stopped asking security
articles about gold impact and economics articles about security relevance, then filled
the hole with a hardcoded "خیلی کم" (score 1) at :2230-2237. The rule requires every axis
to be >= 2, so that sentinel made the floor unreachable and silently suppressed 100% of
security and economics notifications - 0 of 488 security articles alerted, against 50.2%
in production. See test_scoring.py for the regression test built from those records.

An unassessed axis is therefore None and is excluded from the vote. If too few axes were
assessed to decide, the outcome is INSUFFICIENT - a distinct state from "not notable", so
the failure is visible instead of looking like a quiet result.
"""

from __future__ import annotations

from dataclasses import dataclass

from .db import level_score

NOTIFY = "اطلاع‌رسانی شود"
NO_NOTIFY = "اطلاع‌رسانی نشود"
INSUFFICIENT = "ارزیابی ناکافی"

# Legacy thresholds, preserved so the rebuild is comparable before it is retuned.
# Phase 4.4 calibrates these against the golden set instead of assuming them.
HIGH_BAR = 4          # a level of "زیاد" or above counts as a strong signal
HIGH_COUNT_REQUIRED = 2
FLOOR = 2             # no assessed axis may sit below "کم"
MIN_AXES_ASSESSED = 2


@dataclass(frozen=True)
class Decision:
    status: str
    assessed: int
    high: int
    reason: str

    @property
    def notify(self) -> bool:
        return self.status == NOTIFY


def decide(
    confidence_occurrence: str | None,
    gold_price_impact: str | None,
    security_relevance: str | None,
) -> Decision:
    """Decide whether an article warrants notification.

    Each argument is a Persian level string, or None when that axis was not assessed.
    Passing a sentinel level for an unassessed axis is the bug this function exists to
    prevent - pass None.
    """
    scores = [
        level_score(confidence_occurrence),
        level_score(gold_price_impact),
        level_score(security_relevance),
    ]
    assessed = [s for s in scores if s is not None]

    if len(assessed) < MIN_AXES_ASSESSED:
        return Decision(INSUFFICIENT, len(assessed), 0,
                        f"only {len(assessed)} axis assessed, need {MIN_AXES_ASSESSED}")

    high = sum(1 for s in assessed if s >= HIGH_BAR)
    floor_ok = min(assessed) >= FLOOR

    if high >= HIGH_COUNT_REQUIRED and floor_ok:
        return Decision(NOTIFY, len(assessed), high, f"{high} strong axes, floor met")
    if not floor_ok:
        return Decision(NO_NOTIFY, len(assessed), high, f"floor not met (min={min(assessed)})")
    return Decision(NO_NOTIFY, len(assessed), high, f"only {high} strong axes")


if __name__ == "__main__":
    z, k, m, b, bb = "خیلی کم", "کم", "متوسط", "زیاد", "خیلی زیاد"

    assert decide(b, b, m).status == NOTIFY
    assert decide(bb, bb, bb).status == NOTIFY
    assert decide(b, b, z).status == NO_NOTIFY, "floor violation must block"
    assert decide(b, m, m).status == NO_NOTIFY, "one strong axis is not enough"

    # The legacy bug: a strong security article whose gold axis was never assessed.
    # Sentinel -> suppressed (the shipped behaviour). None -> decided on real evidence.
    assert decide(b, z, b).status == NO_NOTIFY, "sentinel reproduces the legacy suppression"
    assert decide(b, None, b).status == NOTIFY, "unassessed axis must not veto"

    assert decide(b, None, None).status == INSUFFICIENT
    assert decide(None, None, None).assessed == 0
    print("scoring: all checks passed")
