"""The notification decision.

FROZEN INVARIANT (2/4), and the reason this whole system was rebuilt.

An unassessed axis is None and is EXCLUDED from the vote - never replaced by a sentinel
level. Legacy substituted «خیلی کم» (score 1) for axes its category-specific prompts never
asked about. That made the floor unreachable and silently suppressed 100% of security and
economics alerts: 0 of 488 security articles, against 50.2% in production.

If too few axes were assessed to decide, the outcome is INSUFFICIENT - a distinct state
from "not notable". Collapsing those two is the same class of error as the sentinel.
"""

from __future__ import annotations

from dataclasses import dataclass

from .vocabulary import LEVELS, NotifyStatus

# Legacy thresholds, preserved so the rebuild stays comparable until it is deliberately
# retuned against human labels.
HIGH_BAR = 4              # «زیاد» or above counts as a strong signal
HIGH_COUNT_REQUIRED = 2
FLOOR = 2                 # no assessed axis may sit below «کم»
MIN_AXES_ASSESSED = 2


def level_score(level: str | None) -> int | None:
    """Ordinal position of a level, or None if absent/unrecognised - never a default.

    Returning 0 or 1 for an unknown value is precisely the bug this module exists to
    prevent, so an unrecognised string is None and drops out of the vote.
    """
    if not level:
        return None
    try:
        return LEVELS.index(level) + 1
    except ValueError:
        return None


@dataclass(frozen=True)
class Decision:
    status: str
    assessed: int
    high: int
    reason: str

    @property
    def notify(self) -> bool:
        return self.status == NotifyStatus.NOTIFY


def decide(
    confidence_occurrence: str | None,
    gold_price_impact: str | None,
    security_relevance: str | None,
) -> Decision:
    """Each argument is a Persian level string, or None when that axis was not assessed."""
    assessed = [
        score
        for score in map(
            level_score, (confidence_occurrence, gold_price_impact, security_relevance)
        )
        if score is not None
    ]
    if len(assessed) < MIN_AXES_ASSESSED:
        return Decision(
            NotifyStatus.INSUFFICIENT,
            len(assessed),
            0,
            f"only {len(assessed)} axis assessed, need {MIN_AXES_ASSESSED}",
        )

    high = sum(score >= HIGH_BAR for score in assessed)
    if min(assessed) < FLOOR:
        return Decision(
            NotifyStatus.NO_NOTIFY, len(assessed), high, f"floor not met (min={min(assessed)})"
        )
    if high >= HIGH_COUNT_REQUIRED:
        return Decision(
            NotifyStatus.NOTIFY, len(assessed), high, f"{high} strong axes, floor met"
        )
    return Decision(NotifyStatus.NO_NOTIFY, len(assessed), high, f"only {high} strong axes")
