"""Stored-time counts must not change when an existing article is fetched again."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from articles.models import Article
from core.collection import collection_summary, coverage_summary
from sources.models import CoverageInterval, CrawlAttempt

pytestmark = pytest.mark.django_db


def test_collection_uses_first_storage_day_and_separates_repeat_sightings(article, source):
    tehran = ZoneInfo("Asia/Tehran")
    now = datetime(2026, 9, 28, 12, tzinfo=tehran)
    Article.objects.filter(pk=article.pk).update(
        created_at=datetime(2026, 9, 27, 23, 30, tzinfo=tehran),
        fetched_at=now,
    )
    CrawlAttempt.objects.create(
        source=source, started_at=now, finished_at=now,
        status="success", fetched=1, repeated=1,
    )

    summary = collection_summary(days=2, now=now)

    assert summary["today"] == 0
    assert summary["new"] == 1
    assert summary["daily"][0]["sources"][source.name] == 1
    assert summary["daily"][1]["sources"][source.name] == 0
    assert summary["attempt_totals"]["repeated"] == 1


def test_coverage_reports_open_gap_and_week_gap_hours(source):
    now = datetime(2026, 10, 2, 12, tzinfo=ZoneInfo("UTC"))
    CoverageInterval.objects.create(
        source=source, state="covered",
        started_at=now - timedelta(days=9), ended_at=now - timedelta(hours=3),
    )
    CoverageInterval.objects.create(
        source=source, state="gap", error_class="blocked",
        started_at=now - timedelta(hours=3), ended_at=now - timedelta(minutes=1),
    )

    row = coverage_summary(now=now)["sources"][0]

    assert row["gap_hours_7d"] == 3.0
    assert row["open_gap"] == {
        "state": "gap", "error_class": "blocked", "since": now - timedelta(hours=3),
    }
    # Twelve quiet minutes later nobody is looking: unknown, not a continued failure.
    later = coverage_summary(now=now + timedelta(minutes=12))["sources"][0]
    assert later["open_gap"]["state"] == "unknown"
