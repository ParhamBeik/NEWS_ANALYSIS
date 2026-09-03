"""The ordinal score vocabulary and the notification decision.

An unassessed axis is None and is excluded from the vote - never a sentinel level.
Legacy substituted "خیلی کم" (score 1) for axes its prompts never asked about, which made
the floor unreachable and silently suppressed 100% of security and economics alerts:
0 of 488 security articles, against 50.2% in production. If too few axes were assessed to
decide, the outcome is INSUFFICIENT, a distinct state from "not notable".
"""

from __future__ import annotations

from dataclasses import dataclass

# Ordinal scale, weakest to strongest. The team's own workbook vocabulary.
LEVELS: tuple[str, ...] = ("خیلی کم", "کم", "متوسط", "زیاد", "خیلی زیاد")

# The three axes `decide()` votes over, in the order it takes them. Storage columns,
# review-form fields, KPI rows and golden-set keys all use these exact names.
AXES: tuple[str, ...] = ("confidence_occurrence", "gold_price_impact", "security_relevance")

NOTIFY = "اطلاع‌رسانی شود"
NO_NOTIFY = "اطلاع‌رسانی نشود"
INSUFFICIENT = "ارزیابی ناکافی"

# Legacy thresholds, preserved so the rebuild stays comparable until it is retuned.
HIGH_BAR = 4              # "زیاد" or above counts as a strong signal
HIGH_COUNT_REQUIRED = 2
FLOOR = 2                 # no assessed axis may sit below "کم"
MIN_AXES_ASSESSED = 2


def level_score(level: str | None) -> int | None:
    """Ordinal position of a level, or None if absent/unrecognised - never a default."""
    try:
        return LEVELS.index(level) + 1 if level else None
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
        return self.status == NOTIFY


def decide(
    confidence_occurrence: str | None,
    gold_price_impact: str | None,
    security_relevance: str | None,
) -> Decision:
    """Each argument is a Persian level string, or None when that axis was not assessed."""
    assessed = [
        score
        for score in map(level_score, (confidence_occurrence, gold_price_impact, security_relevance))
        if score is not None
    ]
    if len(assessed) < MIN_AXES_ASSESSED:
        return Decision(INSUFFICIENT, len(assessed), 0,
                        f"only {len(assessed)} axis assessed, need {MIN_AXES_ASSESSED}")

    high = sum(score >= HIGH_BAR for score in assessed)
    if min(assessed) < FLOOR:
        return Decision(NO_NOTIFY, len(assessed), high, f"floor not met (min={min(assessed)})")
    if high >= HIGH_COUNT_REQUIRED:
        return Decision(NOTIFY, len(assessed), high, f"{high} strong axes, floor met")
    return Decision(NO_NOTIFY, len(assessed), high, f"only {high} strong axes")


if __name__ == "__main__":
    z, k, m, b, bb = LEVELS

    assert decide(b, b, m).status == NOTIFY
    assert decide(bb, bb, bb).status == NOTIFY
    assert decide(b, b, z).status == NO_NOTIFY, "floor violation must block"
    assert decide(b, m, m).status == NO_NOTIFY, "one strong axis is not enough"
    # The legacy bug: a strong security article whose gold axis was never assessed.
    assert decide(b, z, b).status == NO_NOTIFY, "sentinel reproduces the legacy suppression"
    assert decide(b, None, b).status == NOTIFY, "unassessed axis must not veto"
    assert decide(b, None, None).status == INSUFFICIENT
    assert decide(None, None, None).assessed == 0
    assert level_score(None) is None and level_score("nonsense") is None
    print("scoring: all checks passed")
