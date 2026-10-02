"""A transiently failed article page is fetched later, with backoff, until it lands."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from articles.models import Article
from core.errors import Gone, Transient
from sources.extraction import RawArticle
from sources.models import FetchRetry, Source, Strategy
from sources.strategies import khabarfoori
from sources.tasks import drain_fetch_retries

URL = "https://www.khabarfoori.com/news/1/x"


@pytest.fixture
def listing_source(db):
    return Source.objects.create(
        name="khabarfoori", strategy=Strategy.LISTING_DETAIL, url="https://www.khabarfoori.com/"
    )


def _due():
    FetchRetry.objects.update(next_at=timezone.now() - timedelta(seconds=1))


@pytest.mark.django_db
def test_failed_detail_page_is_retried_with_backoff_then_stored(listing_source):
    with (
        patch.object(khabarfoori, "collect_urls", return_value=[URL, URL + "/gone"]),
        patch.object(khabarfoori, "fetch_text", side_effect=[
            Transient("fetch failed: Read timed out"), Gone("HTTP 404"),
        ]),
    ):
        assert khabarfoori.fetch(listing_source, None, limit=2) == []
    retry = FetchRetry.objects.get()  # the 404 is not worth retrying
    assert (retry.url, retry.attempts, retry.error_class) == (URL, 1, "network")

    _due()
    with patch("sources.tasks.strategies.fetch_one", side_effect=Transient("HTTP 503")):
        assert drain_fetch_retries()["rescheduled"] == 1
    retry.refresh_from_db()
    assert retry.attempts == 2
    assert retry.next_at > timezone.now() + timedelta(minutes=9)

    _due()
    raw = RawArticle(source="khabarfoori", url=URL, title="تیتر", content="متن کامل " * 40)
    with patch("sources.tasks.strategies.fetch_one", return_value=raw):
        assert drain_fetch_retries()["stored"] == 1
    assert not FetchRetry.objects.exists()
    assert Article.objects.filter(url=URL).exists()


@pytest.mark.django_db
def test_retry_gives_up_after_max_attempts(listing_source):
    FetchRetry.objects.create(
        source=listing_source, url=URL, attempts=FetchRetry.MAX_ATTEMPTS - 1,
        next_at=timezone.now(),
    )
    with patch("sources.tasks.strategies.fetch_one", side_effect=Transient("timeout")):
        assert drain_fetch_retries()["gave_up"] == 1
    assert FetchRetry.objects.get().gave_up
