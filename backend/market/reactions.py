"""Event-level back-test: how much did the relevant assets move around an important event?

Three rules keep the numbers honest:

1. Prices come only from Portfolio (`market.portfolio`), the single price authority. When it
   is not configured or not answering the sweep skips, logs, and counts the skip where /ops
   can see it. It never fails and never invents a price.
2. Windows follow the market. 24-hour global markets get two hours either side of the
   event (`2h`) and one day after (`1d`). Iranian markets close on Fridays and holidays, so
   they get one and three TRADING days (`1td`, `3td`), counted by `nth_trading_day` - the
   same walk the TGJU back-test uses.
3. A move is judged against the asset's own trailing 30 days of daily moves (`abs_z`). A 1%
   move is noise for bitcoin and an event for the rial; a raw percentage cannot say which.
"""

from __future__ import annotations

import logging
import statistics
from bisect import bisect_right
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise

from django.core.cache import cache
from django.db.models import Avg, Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import portfolio
from .models import EventReaction, nth_trading_day

logger = logging.getLogger(__name__)

MIN_TIER = 3
RELEVANCE_MIN = 50  # asset_scores are 0-100; the reader timeline uses the same bar
LOOKBACK = timedelta(days=30)
Z_TRAILING = timedelta(days=30)
Z_MIN_MOVES = 10
HIT_Z = 1.0
EVENT_LIMIT = 300

GLOBAL_WINDOWS = ("2h", "1d")
IRANIAN_WINDOWS = ("1td", "3td")
IRANIAN_CURRENCIES = {"IRR", "IRT", "TOMAN"}
IRANIAN_KEYS = {"tedpix", "usd_irr", "eur_irr", "gold_18k", "coin_emami"}
#: Watch-item slugs whose Portfolio key differs from the slug.
WATCH_KEYS = {"tse_index": "tedpix", "bitcoin": "btc_usd", "crude_oil": "brent"}

UNAVAILABLE_KEY = "market:reactions:unavailable"
LAST_RUN_KEY = "market:reactions:last_run"
STATUS_TTL = 30 * 24 * 3600

Point = tuple[datetime, Decimal]


# ------------------------------------------------------------------------- pure math


def parse_points(rows) -> list[Point]:
    """Portfolio series rows -> sorted (aware datetime, positive Decimal) pairs."""
    points = []
    for row in rows or []:
        try:
            observed = parse_datetime(str(row.get("observed_at") or ""))
            price = Decimal(str(row.get("price")))
        except (InvalidOperation, ValueError, TypeError, AttributeError):
            continue
        if observed is None or timezone.is_naive(observed) or not price.is_finite() or price <= 0:
            continue
        points.append((observed, price))
    return sorted(points)


def _last_at_or_before(points: list[Point], moment: datetime) -> Point | None:
    index = bisect_right([observed for observed, _ in points], moment)
    return points[index - 1] if index else None


def window_prices(
    points: list[Point], event_time: datetime, window: str, now: datetime
) -> tuple[Point, Point] | None:
    """(before, after) for one window, or None when the market has not answered yet or the
    series has no observation close enough to the edges to mean anything."""
    if window == "2h":
        start, end, slack = event_time - timedelta(hours=2), event_time + timedelta(hours=2), (
            timedelta(hours=1)
        )
    elif window == "1d":
        start, end, slack = event_time, event_time + timedelta(days=1), timedelta(days=1)
    elif window in ("1td", "3td"):
        start, slack = event_time, timedelta(days=4)  # Thursday close before a long weekend
        end = nth_trading_day((observed for observed, _ in points), event_time, int(window[0]))
        if end is None:
            return None
    else:
        raise ValueError(f"unknown window {window!r}")
    if end > now:
        return None
    before = _last_at_or_before(points, start)
    after = _last_at_or_before(points, end)
    if before is None or after is None or start - before[0] > slack:
        return None
    # The after-price must be observed after the event, or the "reaction" is a stale quote.
    if after[0] <= event_time or after[0] == before[0]:
        return None
    return before, after


def pct_change(before: Decimal, after: Decimal) -> float:
    return float((after - before) / before * 100)


def abs_z(change_pct: float, daily: list[Point], event_time: datetime) -> float | None:
    """|change| in units of the standard deviation of the trailing 30 days' daily moves."""
    trailing = [price for observed, price in daily
                if event_time - Z_TRAILING <= observed <= event_time]
    moves = [pct_change(a, b) for a, b in pairwise(trailing)]
    if len(moves) < Z_MIN_MOVES:
        return None
    spread = statistics.pstdev(moves)
    return abs(change_pct) / spread if spread > 0 else None


def is_iranian(row: dict) -> bool:
    return (
        (row.get("currency") or "").upper() in IRANIAN_CURRENCIES
        or row.get("key") in IRANIAN_KEYS
    )


def windows_for(row: dict) -> tuple[str, ...]:
    return IRANIAN_WINDOWS if is_iranian(row) else GLOBAL_WINDOWS


# --------------------------------------------------------------------------- relevance


def relevant_keys(asset_scores: dict, watch_slugs, catalog_rows: dict[str, dict]) -> set[str]:
    """Catalog keys an event is about: Jev asset classes scored ≥ RELEVANCE_MIN, plus
    asset watch items that name a catalog key."""
    classes = {name for name, score in (asset_scores or {}).items()
               if isinstance(score, int | float) and score >= RELEVANCE_MIN}
    keys = {portfolio.LEGACY_KEYS.get(name, name) for name in classes}
    keys |= {key for key, row in catalog_rows.items() if row.get("asset_class") in classes}
    keys |= {WATCH_KEYS.get(slug, portfolio.LEGACY_KEYS.get(slug, slug)) for slug in watch_slugs}
    return keys & catalog_rows.keys()


def asset_class(key: str, row: dict) -> str:
    if row.get("asset_class"):
        return str(row["asset_class"])[:32]
    reverse = {value: name for name, value in portfolio.LEGACY_KEYS.items()}
    return reverse.get(key, "other")


# ------------------------------------------------------------------------------ status


def _record_unavailable(reason: str) -> None:
    logger.info("event reactions skipped: portfolio %s", reason)
    try:
        if not cache.add(UNAVAILABLE_KEY, 1, STATUS_TTL):
            cache.incr(UNAVAILABLE_KEY)
        cache.set(LAST_RUN_KEY, {"at": timezone.now().isoformat(), "status": "unavailable",
                                 "reason": reason}, STATUS_TTL)
    except Exception:
        logger.warning("could not count a skipped reaction sweep", exc_info=True)


# ------------------------------------------------------------------------------- sweep


def compute(now: datetime | None = None, limit: int = EVENT_LIMIT) -> dict:
    """Store every reaction that the market has answered and that is not stored yet."""
    from articles.models import NewsEvent, WatchItem
    from core import tiers

    now = now or timezone.now()
    catalog = portfolio.catalog()
    if not catalog["available"]:
        _record_unavailable(catalog["reason"])
        return {"status": "unavailable", "reason": catalog["reason"]}
    rows = {row["key"]: row for row in catalog.get("results", []) if row.get("key")}

    cuts = tiers.cutoffs()
    events = (
        NewsEvent.objects.filter(
            event_time__gte=now - LOOKBACK,
            event_time__lte=now - timedelta(hours=2),
            iran_score__isnull=False,
        )
        .exclude(category="other")
        .exclude(status=NewsEvent.Status.WITHDRAWN)
        .prefetch_related("assessments", "watch_links__item")
        .order_by("-event_time")
    )
    done = set(
        EventReaction.objects.filter(event__in=events).values_list("event_id", "asset_key",
                                                                   "window")
    )
    work, counted = [], 0
    for event in events:
        if counted >= limit:
            break
        tier = tiers.tier(tiers.impact(event.iran_score, event.global_score), "impact", cuts)
        if tier is None or tier < MIN_TIER:
            continue
        latest = max(event.assessments.all(), key=lambda row: row.id, default=None)
        slugs = [link.item.slug for link in event.watch_links.all()
                 if link.item.kind == WatchItem.Kind.ASSET]
        before = len(work)
        for key in sorted(relevant_keys(latest.asset_scores if latest else {}, slugs, rows)):
            pending = [w for w in windows_for(rows[key]) if (event.id, key, w) not in done]
            if pending:
                work.append((event, tier, key, pending))
        counted += len(work) > before

    daily, intraday = {}, {}
    span = (now - min((item[0].event_time for item in work), default=now)).days + 2
    stored = waiting = 0
    for event, tier, key, pending in work:
        if key not in daily:
            daily[key] = parse_points(
                portfolio.series(key, days=span + Z_TRAILING.days, until=now.date())
                .get("points")
            )
            intraday[key] = [] if is_iranian(rows[key]) else parse_points(
                portfolio.series(key, days=span, until=now.date(), interval="1h").get("points")
            )
        for window in pending:
            series = intraday[key] if window == "2h" or intraday[key] else daily[key]
            prices = window_prices(series, event.event_time, window, now)
            if prices is None:
                waiting += 1
                continue
            (_, before), (_, after) = prices
            change = pct_change(before, after)
            EventReaction.objects.get_or_create(
                event=event, asset_key=key, window=window,
                defaults={
                    "asset_class": asset_class(key, rows[key]),
                    "tier": tier,
                    "price_before": before,
                    "price_after": after,
                    "pct_change": round(change, 4),
                    "abs_z": abs_z(change, daily[key], event.event_time),
                },
            )
            stored += 1
    result = {"status": "ok", "stored": stored, "not_yet_answerable": waiting}
    try:
        cache.set(LAST_RUN_KEY, {"at": now.isoformat(), **result}, STATUS_TTL)
    except Exception:
        logger.warning("could not record the reaction sweep", exc_info=True)
    return result


# ------------------------------------------------------------------------- calibration


def _summary(queryset, field: str) -> list[dict]:
    rows = (
        queryset.values(field)
        .annotate(
            reactions=Count("id"),
            scored=Count("id", filter=Q(abs_z__isnull=False)),
            hits=Count("id", filter=Q(abs_z__gte=HIT_Z)),
            mean_abs_z=Avg("abs_z"),
        )
        .order_by(field)
    )
    return [
        {
            "key": row[field],
            "reactions": row["reactions"],
            "scored": row["scored"],
            "mean_abs_z": round(row["mean_abs_z"], 3) if row["mean_abs_z"] is not None else None,
            "hit_rate": round(row["hits"] / row["scored"], 3) if row["scored"] else None,
        }
        for row in rows
    ]


def calibration(days: int = 90) -> dict:
    """Per tier and per asset class: mean |z| and the share of reactions with |z| ≥ 1.

    If tiers mean anything, both rise with the tier. Sample sizes travel with every number.
    """
    reactions = EventReaction.objects.filter(computed_at__gte=timezone.now() - timedelta(days=days))
    return {
        "window_days": days,
        "hit_z": HIT_Z,
        "configured": portfolio.configured(),
        "unavailable_runs": cache.get(UNAVAILABLE_KEY, 0),
        "last_run": cache.get(LAST_RUN_KEY),
        "by_tier": _summary(reactions, "tier"),
        "by_asset_class": _summary(reactions, "asset_class"),
    }
