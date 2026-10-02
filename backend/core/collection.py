"""Calendar-day collection evidence. Sightings never count as newly stored articles."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count, Max, Min, Prefetch, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from articles.models import Article
from inference.models import Classification, Evaluation, NodeEvent, ProviderCircuit
from sources.models import CoverageInterval, CrawlAttempt, FetchRetry, Source

TEHRAN = ZoneInfo("Asia/Tehran")
STALE_AFTER = timedelta(minutes=15)
INTERRUPTED_AFTER = timedelta(minutes=30)


def day_bounds(day):
    start = datetime.combine(day, time.min, tzinfo=TEHRAN)
    return start, start + timedelta(days=1)


def attempt_data(attempt, now):
    status = attempt.status
    if status == "running" and now - attempt.started_at > INTERRUPTED_AFTER:
        status = "interrupted"
    return {
        "id": attempt.pk, "source": attempt.source_id, "status": status,
        "started_at": attempt.started_at, "finished_at": attempt.finished_at,
        "new": attempt.new, "repeated": attempt.repeated,
        "fetched": attempt.fetched, "failed": attempt.failed, "error": attempt.error,
        "retry": attempt.retry,
    }


def collection_summary(days=14, now=None):
    now = now or timezone.now()
    today = now.astimezone(TEHRAN).date()
    first = today - timedelta(days=days - 1)
    start, _ = day_bounds(first)
    articles = Article.objects.filter(created_at__gte=start, created_at__lte=now)
    grouped = list(articles.annotate(day=TruncDate("created_at", tzinfo=TEHRAN))
                   .values("day", "source_id").annotate(count=Count("id")).order_by())
    by_day = {first + timedelta(days=i): {} for i in range(days)}
    totals = {}
    for row in grouped:
        by_day[row["day"]][row["source_id"]] = row["count"]
        totals[row["source_id"]] = totals.get(row["source_id"], 0) + row["count"]

    sources = []
    for source in Source.objects.prefetch_related(Prefetch(
        "crawl_attempts", queryset=CrawlAttempt.objects.order_by("-started_at", "-id")[:1],
        to_attr="latest_attempt",
    )).annotate(last_new=Max("articles__created_at")):
        attempt = source.latest_attempt[0] if source.latest_attempt else None
        latest = attempt_data(attempt, now) if attempt else None
        if not source.enabled:
            state = "disabled"
        elif latest and latest["status"] in {"failed", "partial", "empty", "interrupted"}:
            state = latest["status"]
        elif attempt and attempt.finished_at and now - attempt.finished_at <= STALE_AFTER:
            state = "healthy"
        elif attempt and latest["status"] == "running":
            state = "running"
        else:
            state = "stale" if source.last_new else "unknown"
        sources.append({
            "name": source.name, "display_name": source.display_name or source.name,
            "enabled": source.enabled, "state": state, "last_new_at": source.last_new,
            "new": totals.get(source.name, 0), "today": by_day[today].get(source.name, 0),
            "latest_attempt": latest,
        })

    attempts = CrawlAttempt.objects.filter(started_at__gte=start, started_at__lte=now)
    return {
        "as_of": now, "timezone": "Asia/Tehran", "days": days,
        "stale_after_minutes": 15, "interrupted_after_minutes": 30,
        "today": sum(by_day[today].values()), "new": sum(totals.values()),
        "tracking_started_at": CrawlAttempt.objects.aggregate(at=Min("started_at"))["at"],
        "attempt_totals": attempts.aggregate(
            attempts=Count("id"), repeated=Sum("repeated"), failed=Sum("failed"),
        ),
        "quality": articles.aggregate(
            duplicates=Count("id", filter=Q(duplicate_of__isnull=False)),
            feed_only=Count("id", filter=Q(extraction_tier__in=["feed", "listing"])),
            empty_body=Count("id", filter=Q(content="")),
            quality_flagged=Count("id", filter=~Q(quality_flag="")),
        ),
        "daily": [{"day": day, "new": sum(counts.values()),
                   "sources": {s["name"]: counts.get(s["name"], 0) for s in sources}}
                  for day, counts in by_day.items()],
        "sources": sources,
        "recent_attempts": [attempt_data(a, now) for a in attempts[:20]],
    }


def analysis_summary(stage):
    """Coverage is articles with a result, not task attempts or an inferred queue length."""
    model = Classification if stage == "classification" else Evaluation
    rows = model.objects.filter(pk__in=model.objects.latest_ids())
    total = Article.objects.count()
    completed = rows.count()
    now = timezone.now()
    events = NodeEvent.objects.filter(
        node="classify" if stage == "classification" else "evaluate",
        created_at__gte=now - timedelta(hours=24),
    )
    return {
        "as_of": now, "total": total, "completed": completed,
        "without_result": total - completed,
        "last_result_at": rows.aggregate(at=Max("created_at"))["at"],
        "categories": list(rows.values("category").annotate(count=Count("id")).order_by())
        if stage == "classification" else [],
        "events_24h": list(events.values("status").annotate(count=Count("id")).order_by()),
        "circuit": ProviderCircuit.objects.values("state", "next_probe_at").first(),
    }


COVERAGE_WINDOW = timedelta(days=7)


def _hours_within(rows, state, since, now):
    seconds = sum(
        (min(row.ended_at, now) - max(row.started_at, since)).total_seconds()
        for row in rows if row.state == state
    )
    return round(max(seconds, 0) / 3600, 1)


def coverage_summary(now=None):
    """Per source: who it speaks for, whether it is being watched, and for how long it was
    not over the last week. `open_gap` is the gap still running now, if any; a source with
    no crawl for longer than CoverageInterval.UNOBSERVED_AFTER is reported as `unknown`
    because nobody looked, not because it failed."""
    now = now or timezone.now()
    since = now - COVERAGE_WINDOW
    intervals = {}
    for row in CoverageInterval.objects.filter(ended_at__gte=since).order_by("ended_at", "id"):
        intervals.setdefault(row.source_id, []).append(row)
    retries = dict(
        FetchRetry.objects.filter(gave_up=False).values("source_id")
        .annotate(count=Count("id")).values_list("source_id", "count")
    )
    rows = []
    for source in Source.objects.prefetch_related(Prefetch(
        "crawl_attempts", queryset=CrawlAttempt.objects.order_by("-started_at", "-id")[:1],
        to_attr="latest_attempt",
    )):
        own = intervals.get(source.name, [])
        latest = own[-1] if own else None
        open_gap = None
        if latest is None or now - latest.ended_at > CoverageInterval.UNOBSERVED_AFTER:
            open_gap = {"state": CoverageInterval.UNKNOWN, "error_class": "",
                        "since": latest.ended_at if latest else None}
        elif latest.state != CoverageInterval.COVERED:
            open_gap = {"state": latest.state, "error_class": latest.error_class,
                        "since": latest.started_at}
        attempt = source.latest_attempt[0] if source.latest_attempt else None
        rows.append({
            "name": source.name, "display_name": source.display_name or source.name,
            "enabled": source.enabled, "language": source.language,
            "independence_group": source.independence_group, "role": source.role,
            "license_mode": source.license_mode, "health": source.health_status,
            "last_success_at": source.last_success_at, "open_gap": open_gap,
            "gap_hours_7d": _hours_within(own, CoverageInterval.GAP, since, now),
            "unknown_hours_7d": _hours_within(own, CoverageInterval.UNKNOWN, since, now),
            "error_class": attempt.error_class if attempt else "",
            "retries_pending": retries.get(source.name, 0),
        })
    return {"as_of": now, "window_days": COVERAGE_WINDOW.days, "sources": rows}
