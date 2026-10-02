"""The staff operations picture: AI cost, crawl errors by cause, and freshness SLOs.

No tables of its own. Everything is computed from rows the pipeline already writes
(AIUsageRecord, CrawlAttempt, CoverageInterval, Article, NewsEvent) plus the Redis budget
counters - with one exception: event-pipeline AI FAILURES are not stored anywhere durable
(AIUsageRecord records only calls that returned a bill), so they are counted here as
small expiring per-day cache counters. Losing them on a Redis flush costs a week of a
chart, not data.

Times: "today" and "this month" are UTC, because that is how `inference.budget` keys the
ceilings this page compares against.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, F, Min, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from articles.models import Article, NewsEvent
from core import tiers
from core.collection import coverage_summary
from core.errors import ERROR_CLASSES, BudgetExceeded, Fatal, Permanent, Transient
from core.watch import watched_events
from inference import budget, circuit
from inference.models import AIUsageRecord, CircuitState
from sources.models import CrawlAttempt, Source

logger = logging.getLogger(__name__)

AI_STAGES = ("jev", "brief", "title", "storyline")
FAILURE_KINDS = ("budget", "fatal", "permanent", "transient", "invalid_answer", "other")
FAILURE_DAYS = 7
FAILURE_TTL = 60 * 60 * 24 * (FAILURE_DAYS + 1)

DISCOVERY_TARGET = timedelta(minutes=5)
BRIEF_TARGET = timedelta(minutes=10)
PRIORITY_GAP_ALERT = timedelta(minutes=30)
OPEN_CIRCUIT_STATES = (CircuitState.OPEN_BUDGET, CircuitState.OPEN_ERRORS, CircuitState.STOPPED)


# ------------------------------------------------------------------ AI failure counters


def _failure_key(day, stage: str, kind: str) -> str:
    return f"ops:aifail:{day:%Y%m%d}:{stage}:{kind}"


def record_ai_failure(stage: str, kind: str, *, now=None) -> None:
    """Count one failed AI call. Never raises: bookkeeping must not fail the task."""
    kind = kind if kind in FAILURE_KINDS else "other"
    key = _failure_key((now or timezone.now()).astimezone(UTC).date(), stage, kind)
    try:
        if not cache.add(key, 1, FAILURE_TTL):
            cache.incr(key)
    except Exception:
        logger.warning("could not count AI failure %s/%s", stage, kind, exc_info=True)


def failure_kind(exc: BaseException) -> str:
    for cls, kind in ((BudgetExceeded, "budget"), (Fatal, "fatal"),
                      (Permanent, "permanent"), (Transient, "transient")):
        if isinstance(exc, cls):
            return kind
    return "other"


# ----------------------------------------------------------------------------- AI cost


def _usage_breakdown(rows, field: str, day_start) -> list[dict]:
    return [
        {field: row[field], "calls": row["calls"], "cost_usd": float(row["cost"] or 0),
         "today_usd": float(row["today"] or 0)}
        for row in rows.values(field).annotate(
            calls=Count("id"), cost=Sum("cost_usd"),
            today=Sum("cost_usd", filter=Q(created_at__gte=day_start)),
        ).order_by(field)
    ]


def pause_reason(circuit_state: str, month_usd: float, day_usd: float) -> str:
    """Why no AI call can run right now, or "" when nothing is in the way."""
    if circuit_state == CircuitState.OPEN_BUDGET:
        return "wallet_empty"
    if circuit_state in OPEN_CIRCUIT_STATES:
        return "circuit_open"
    if month_usd >= settings.NEWS_MONTHLY_BUDGET_USD:
        return "monthly_budget"
    if day_usd >= settings.NEWS_DAILY_BUDGET_USD:
        return "daily_budget"
    return ""


def ai_cost(now=None) -> dict:
    now = now or timezone.now()
    day_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    month_rows = AIUsageRecord.objects.filter(created_at__gte=month_start, created_at__lte=now)

    stages = {stage: {"stage": stage, "calls": 0, "cost_usd": 0.0, "today_usd": 0.0}
              for stage in AI_STAGES}
    for row in _usage_breakdown(month_rows, "stage", day_start):
        stages[row["stage"]] = row

    first_day = now.astimezone(UTC).date() - timedelta(days=FAILURE_DAYS - 1)
    days = [first_day + timedelta(days=i) for i in range(FAILURE_DAYS)]
    calls = dict(
        AIUsageRecord.objects.filter(
            created_at__gte=datetime.combine(first_day, time.min, tzinfo=UTC), created_at__lte=now
        )
        .annotate(day=TruncDate("created_at", tzinfo=UTC)).values("day")
        .annotate(calls=Count("id")).values_list("day", "calls")
    )
    keys = {(day, stage, kind): _failure_key(day, stage, kind)
            for day in days for stage in AI_STAGES for kind in FAILURE_KINDS}
    counts = cache.get_many(list(keys.values()))
    daily = []
    for day in days:
        failures = {}
        for (key_day, _stage, kind), key in keys.items():
            if key_day == day and counts.get(key):
                failures[kind] = failures.get(kind, 0) + int(counts[key])
        daily.append({"day": day, "calls": calls.get(day, 0), "failures": failures})

    month_usd, day_usd = budget.month_spend(), budget.day_spend()
    state = circuit.snapshot()
    return {
        "as_of": now,
        "month": {"spent_usd": month_usd, "ceiling_usd": settings.NEWS_MONTHLY_BUDGET_USD,
                  "recorded_usd": sum(row["cost_usd"] for row in stages.values())},
        "today": {"spent_usd": day_usd, "ceiling_usd": settings.NEWS_DAILY_BUDGET_USD,
                  "recorded_usd": sum(row["today_usd"] for row in stages.values())},
        "by_stage": list(stages.values()),
        "by_provider": _usage_breakdown(month_rows, "provider", day_start),
        "daily": daily,
        "failure_kinds": FAILURE_KINDS,
        "failures_7d": {kind: sum(row["failures"].get(kind, 0) for row in daily)
                        for kind in FAILURE_KINDS},
        "circuit": state,
        "paused": pause_reason(state["state"], month_usd, day_usd),
    }


# ------------------------------------------------------------------------ crawl errors


def crawl_errors(now=None) -> dict:
    """Failed crawl attempts by cause and source, last 24 hours and last 7 days."""
    now = now or timezone.now()
    rows = list(
        CrawlAttempt.objects.filter(started_at__gte=now - timedelta(days=7), started_at__lte=now)
        .exclude(error_class="")
        .values("source_id", "source__display_name", "error_class")
        .annotate(last_7d=Count("id"),
                  last_24h=Count("id", filter=Q(started_at__gte=now - timedelta(hours=24))))
        .order_by("-last_24h", "-last_7d", "source_id", "error_class")
    )
    totals = {name: {"last_24h": 0, "last_7d": 0} for name in ERROR_CLASSES}
    for row in rows:
        total = totals.setdefault(row["error_class"], {"last_24h": 0, "last_7d": 0})
        total["last_24h"] += row["last_24h"]
        total["last_7d"] += row["last_7d"]
    return {
        "as_of": now,
        "classes": list(ERROR_CLASSES),
        "totals": totals,
        "rows": [
            {"source": row["source_id"],
             "display_name": row["source__display_name"] or row["source_id"],
             "error_class": row["error_class"],
             "last_24h": row["last_24h"], "last_7d": row["last_7d"]}
            for row in rows
        ],
    }


# ---------------------------------------------------------------------- freshness SLOs


def discovery_slo(now, since) -> dict:
    """Tier-1 (priority) source publication to our first storage, target 5 minutes.

    Articles with an uncertain date are left out: their lag would measure the parser.
    """
    articles = Article.objects.filter(
        source__tier=1, date_uncertain=False,
        published_at__gte=since, published_at__lte=now, created_at__lte=now,
    )
    on_time = Q(created_at__lte=F("published_at") + DISCOVERY_TARGET)
    totals = articles.aggregate(total=Count("id"), passed=Count("id", filter=on_time))
    return {
        "target_minutes": int(DISCOVERY_TARGET.total_seconds() // 60),
        "passed": totals["passed"],
        "failed": totals["total"] - totals["passed"],
        "misses_by_source": list(
            articles.exclude(on_time).values("source_id").annotate(count=Count("id"))
            .order_by("-count", "source_id")
        ),
    }


def brief_slo(now, since) -> dict:
    """Brief-eligible events: first seen to brief visible, target 10 minutes.

    Only events the pipeline briefs count (core.tiers.brief_eligible: impact tier >= 4,
    or >= 3 when watched); an event it will never brief is not a miss. The brief
    time is its first `brief` AIUsageRecord, written just before the brief is saved.
    An event still inside its 10 minutes without a brief is `pending`, not failed.
    """
    rows = (
        NewsEvent.objects.filter(first_seen_at__gte=since, first_seen_at__lte=now)
        .exclude(category__in=["", "other"])
        .annotate(brief_at=Min("usage_records__created_at",
                               filter=Q(usage_records__stage="brief")))
        .values("id", "title_fa", "category", "first_seen_at", "iran_score",
                "global_score", "brief_fa", "brief_at")
    )
    passed = failed = pending = 0
    misses = []
    rows = list(rows)
    watched = watched_events(row["id"] for row in rows)
    cuts = tiers.cutoffs()
    for row in rows:
        if not tiers.brief_eligible(row["category"], row["iran_score"], row["global_score"],
                                    watched=row["id"] in watched, cuts=cuts):
            continue
        deadline = row["first_seen_at"] + BRIEF_TARGET
        visible_at = row["brief_at"] if row["brief_fa"] else None
        if visible_at is not None and visible_at <= deadline:
            passed += 1
        elif visible_at is not None or now > deadline:
            failed += 1
            lag = (visible_at or now) - row["first_seen_at"]
            misses.append({"event": row["id"], "title": row["title_fa"][:120],
                           "minutes": round(lag.total_seconds() / 60, 1),
                           "brief_visible": visible_at is not None})
        else:
            pending += 1
    return {
        "target_minutes": int(BRIEF_TARGET.total_seconds() // 60),
        "passed": passed, "failed": failed, "pending": pending,
        "misses": sorted(misses, key=lambda miss: -miss["minutes"])[:10],
    }


def freshness_slo(now=None, window: timedelta = timedelta(hours=24)) -> dict:
    now = now or timezone.now()
    since = now - window
    return {
        "as_of": now,
        "window_hours": round(window.total_seconds() / 3600),
        "discovery": discovery_slo(now, since),
        "brief": brief_slo(now, since),
    }


def priority_gaps(now=None, longer_than: timedelta = PRIORITY_GAP_ALERT) -> list[dict]:
    """Enabled tier-1 sources whose current gap (or silence) has lasted too long."""
    now = now or timezone.now()
    priority = set(Source.objects.filter(enabled=True, tier=1).values_list("name", flat=True))
    gaps = []
    for row in coverage_summary(now=now)["sources"]:
        gap = row["open_gap"]
        if row["name"] not in priority or gap is None:
            continue
        if gap["since"] is None or now - gap["since"] > longer_than:
            gaps.append({"source": row["name"], "display_name": row["display_name"],
                         "state": gap["state"], "error_class": gap["error_class"],
                         "since": gap["since"]})
    return gaps


def staff_ops(now=None) -> dict:
    now = now or timezone.now()
    return {
        "as_of": now,
        "ai": ai_cost(now),
        "crawl_errors": crawl_errors(now),
        "freshness": freshness_slo(now),
        "priority_gaps": priority_gaps(now),
    }
