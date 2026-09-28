"""Stored-time counts must not change when an existing article is fetched again."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from articles.models import Article
from core.collection import collection_summary
from sources.models import CrawlAttempt

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
