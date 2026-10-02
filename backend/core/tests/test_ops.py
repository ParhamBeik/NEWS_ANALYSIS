"""Staff ops aggregations and the deduplicated staff notices."""

from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django_celery_beat.models import PeriodicTask
from rest_framework.test import APIClient

from articles.models import Article, NewsEvent
from core import ops, ops_alerts
from inference import budget, circuit
from inference.models import AIUsageRecord
from sources.models import CoverageInterval, CrawlAttempt, Source, Strategy

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def _usage(stage, provider, cost, at, event=None):
    row = AIUsageRecord.objects.create(
        event=event, stage=stage, provider=provider, model="m", cost_usd=cost
    )
    AIUsageRecord.objects.filter(pk=row.pk).update(created_at=at)


def test_ai_cost_splits_month_and_today_by_stage_and_provider(monkeypatch):
    monkeypatch.setattr(budget, "month_spend", lambda: 4.0)
    monkeypatch.setattr(budget, "day_spend", lambda: 0.5)
    _usage("jev", "TypeSafe", "0.10", NOW - timedelta(hours=1))
    _usage("brief", "GapGPT", "0.40", NOW - timedelta(days=1))
    _usage("brief", "GapGPT", "9.00", NOW - timedelta(days=40))  # last month: excluded
    ops.record_ai_failure("jev", "budget", now=NOW)
    ops.record_ai_failure("jev", "budget", now=NOW)
    ops.record_ai_failure("brief", "nonsense", now=NOW - timedelta(days=2))

    report = ops.ai_cost(now=NOW)

    stages = {row["stage"]: row for row in report["by_stage"]}
    assert set(stages) == {"jev", "brief", "storyline"}
    assert stages["jev"]["today_usd"] == pytest.approx(0.10)
    assert stages["brief"]["cost_usd"] == pytest.approx(0.40)
    assert stages["brief"]["today_usd"] == 0
    assert stages["storyline"]["calls"] == 0
    providers = {row["provider"]: row["calls"] for row in report["by_provider"]}
    assert providers == {"GapGPT": 1, "TypeSafe": 1}
    assert report["failures_7d"]["budget"] == 2
    assert report["failures_7d"]["other"] == 1
    assert report["daily"][-1]["calls"] == 1
    assert report["month"]["spent_usd"] == 4.0
    assert report["paused"] == ""


def test_pause_reason_names_the_blocker(settings):
    settings.NEWS_MONTHLY_BUDGET_USD = 30
    settings.NEWS_DAILY_BUDGET_USD = 1
    assert ops.pause_reason("open_budget", 0, 0) == "wallet_empty"
    assert ops.pause_reason("open_errors", 0, 0) == "circuit_open"
    assert ops.pause_reason("closed", 30, 0) == "monthly_budget"
    assert ops.pause_reason("closed", 1, 1) == "daily_budget"
    assert ops.pause_reason("probing", 1, 0) == ""


def test_crawl_errors_group_by_cause_and_source(source):
    for hours, cls in ((1, "network"), (2, "network"), (30, "network"), (3, "blocked"),
                       (200, "parse")):
        CrawlAttempt.objects.create(source=source, started_at=NOW - timedelta(hours=hours),
                                    status="failed", error_class=cls)
    CrawlAttempt.objects.create(source=source, started_at=NOW, status="success")

    report = ops.crawl_errors(now=NOW)

    rows = {row["error_class"]: row for row in report["rows"]}
    assert rows["network"]["last_24h"] == 2 and rows["network"]["last_7d"] == 3
    assert rows["blocked"]["last_24h"] == 1
    assert "parse" not in rows
    assert report["totals"]["network"] == {"last_24h": 2, "last_7d": 3}


def test_discovery_slo_counts_priority_articles_only(make_article, source):
    other = Source.objects.create(name="slow", strategy=Strategy.RSS_GENERIC,
                                  url="https://slow.example/rss", tier=3)
    published = NOW - timedelta(hours=2)
    for lag, src in ((2, source), (9, source), (30, other)):
        row = make_article(source=src, published_at=published)
        Article.objects.filter(pk=row.pk).update(created_at=published + timedelta(minutes=lag))
    uncertain = make_article(published_at=published, date_uncertain=True)
    Article.objects.filter(pk=uncertain.pk).update(created_at=published + timedelta(hours=1))

    result = ops.discovery_slo(NOW, NOW - timedelta(hours=24))

    assert (result["passed"], result["failed"]) == (1, 1)
    assert result["misses_by_source"] == [{"source_id": "mehr", "count": 1}]


def _event(article, seen, iran, category="energy", brief=""):
    return NewsEvent.objects.create(
        primary_article=article, event_time=seen, first_seen_at=seen, category=category,
        iran_score=iran, global_score=iran, brief_fa=brief,
    )


def test_brief_slo_passes_fails_and_waits(make_article, settings):
    settings.NEWS_BRIEF_MIN_SCORE = 75
    on_time = _event(make_article(), NOW - timedelta(hours=1), 90, brief="خلاصه")
    _usage("brief", "GapGPT", "0.01", NOW - timedelta(minutes=55), event=on_time)
    late = _event(make_article(), NOW - timedelta(hours=1), 90, brief="خلاصه")
    _usage("brief", "GapGPT", "0.01", NOW - timedelta(minutes=30), event=late)
    _event(make_article(), NOW - timedelta(hours=1), 90)  # never briefed: missed
    _event(make_article(), NOW - timedelta(minutes=3), 90)  # still inside 10 min
    _event(make_article(), NOW - timedelta(hours=1), 65)  # below the brief threshold
    _event(make_article(), NOW - timedelta(hours=1), 95, category="other")

    result = ops.brief_slo(NOW, NOW - timedelta(hours=24))

    assert (result["passed"], result["failed"], result["pending"]) == (1, 2, 1)
    assert [miss["brief_visible"] for miss in result["misses"]] == [False, True]


def test_priority_gap_over_30_minutes_is_reported(source):
    CoverageInterval.objects.create(source=source, started_at=NOW - timedelta(minutes=45),
                                    ended_at=NOW - timedelta(minutes=1), state="gap",
                                    error_class="blocked")
    gaps = ops.priority_gaps(NOW)
    assert [(gap["source"], gap["error_class"]) for gap in gaps] == [("mehr", "blocked")]
    assert ops.priority_gaps(NOW - timedelta(minutes=20)) == []


@override_settings(EMAIL_HOST="smtp.example.invalid", OPS_ALERT_WEBHOOK_URL="https://hook.invalid/x")
def test_notices_are_sent_once_per_condition_per_window(monkeypatch, settings):
    settings.NEWS_MONTHLY_BUDGET_USD = 10
    monkeypatch.setattr(budget, "month_spend", lambda: 8.5)
    circuit.open_budget("wallet empty")
    get_user_model().objects.create_user("ops", "ops@example.invalid", "x", is_staff=True)
    posts = []

    class Ok:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(ops_alerts.requests, "post", lambda url, **kw: posts.append(kw) or Ok())

    first = ops_alerts.notify_staff()
    second = ops_alerts.notify_staff()

    assert first["sent"] == ["budget-month-80", "circuit-open_budget"]
    assert first["channels"] == ["email", "webhook"]
    assert second["conditions"] == first["conditions"] and second["sent"] == []
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["ops@example.invalid"]
    assert len(posts) == 1 and len(posts[0]["json"]["alerts"]) == 2


def test_nothing_is_delivered_when_no_channel_is_configured(monkeypatch, settings):
    settings.EMAIL_HOST = ""
    settings.OPS_ALERT_WEBHOOK_URL = ""
    circuit.open_errors("five errors")
    result = ops_alerts.notify_staff()
    assert result["sent"] == ["circuit-open_errors"] and result["channels"] == []
    assert mail.outbox == []


def test_staff_endpoint_is_staff_only_and_schedule_is_installed(user):
    client = APIClient()
    client.force_authenticate(user)
    assert client.get("/api/ops/staff/").status_code == 403
    user.is_staff = True
    user.save()
    body = client.get("/api/ops/staff/").json()
    assert {"ai", "crawl_errors", "freshness", "priority_gaps"} <= set(body)

    call_command("setup_schedule")
    task = PeriodicTask.objects.get(name="ops-staff-alerts")
    assert task.task == "core.ops_alerts" and task.enabled
