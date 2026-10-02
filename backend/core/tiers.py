"""Reader impact tiers 1-5. The one definition; the frontend displays what the API returns.

A tier is relative: where an event's score falls in the last 30 days of scored events.
Tier 5 is about the top 2%, tier 4 the next 8%, tier 3 the next 20%, tier 2 the next 30%,
and the rest tier 1. A fixed scale would let a quiet month show nothing above "medium"
and a war month show everything as "very high"; readers need a rank, not the raw score.

Jev scores are coarse (mostly multiples of 25), so many events tie. Ties resolve DOWN: an
event reaches a tier only if the share of events scoring at least as high still fits that
tier's share. If 5% of the month scored 100, nothing is tier 5 - inflating the top tier
would make it meaningless. Below MIN_SAMPLE scored events the quantiles are noise, so the
fixed 20-point bands apply; those bands also map Jev's five levels (0, 25, ... 100) onto
tiers 1-5 one-to-one, which is why swipe-review agreement uses them (`band`).
"""

from __future__ import annotations

import math
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

WINDOW = timedelta(days=30)
MIN_SAMPLE = 200
# Largest share of scored events allowed at or above tiers 2, 3, 4 and 5.
TOP_SHARES = (0.60, 0.30, 0.10, 0.02)
FIXED_BANDS = (20, 40, 60, 80)
AXES = ("iran", "global", "impact")
CACHE_KEY = "tiers:cutoffs:v1"
CACHE_SECONDS = 10 * 60


def impact(iran: float | None, global_: float | None) -> float | None:
    """The card's single score: core.events.ranked_events' 60/40 weighting."""
    if iran is None:
        return global_
    if global_ is None:
        return iran
    return 0.6 * iran + 0.4 * global_


def band(score: float | None) -> int | None:
    """Fixed-band tier 1-5. Missing stays missing: unassessed is never "very low"."""
    if score is None:
        return None
    return 1 + sum(score >= cut for cut in FIXED_BANDS)


def quantile_cutoffs(scores: list[float]) -> tuple[float, ...]:
    """Lowest score for tiers 2-5 such that the share at or above it fits TOP_SHARES."""
    counts: dict[float, int] = {}
    for score in scores:
        counts[score] = counts.get(score, 0) + 1
    cuts = []
    for share in TOP_SHARES:
        allowed, at_or_above, cut = share * len(scores), 0, math.inf
        for value in sorted(counts, reverse=True):
            at_or_above += counts[value]
            if at_or_above > allowed:
                break
            cut = value
        cuts.append(cut)
    return tuple(cuts)


def cutoffs() -> dict:
    """Per-axis cut-offs from the rolling window, cached for CACHE_SECONDS."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    from articles.models import NewsEvent

    rows = list(
        NewsEvent.objects.filter(
            event_time__gte=timezone.now() - WINDOW,
            iran_score__isnull=False,
            global_score__isnull=False,
        )
        .exclude(category="other")
        .values_list("iran_score", "global_score")
    )
    if len(rows) < MIN_SAMPLE:
        result = {"basis": "fixed", "sample": len(rows), **dict.fromkeys(AXES, FIXED_BANDS)}
    else:
        result = {
            "basis": "relative",
            "sample": len(rows),
            "iran": quantile_cutoffs([i for i, _ in rows]),
            "global": quantile_cutoffs([g for _, g in rows]),
            "impact": quantile_cutoffs([impact(i, g) for i, g in rows]),
        }
    cache.set(CACHE_KEY, result, CACHE_SECONDS)
    return result


def tier(score: float | None, axis: str, cuts: dict | None = None) -> int | None:
    if score is None:
        return None
    cuts = cuts or cutoffs()
    return 1 + sum(score >= cut for cut in cuts[axis])
