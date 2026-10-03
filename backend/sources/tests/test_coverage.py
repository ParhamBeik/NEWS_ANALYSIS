"""Coverage is compact, contiguous, and honest about silences."""

from datetime import timedelta
from unittest.mock import patch

import pytest
import requests
from django.utils import timezone

from core.errors import Gone, Transient, error_class
from sources.models import CoverageInterval, CrawlAttempt
from sources.tasks import crawl_source


def _http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=response)


@pytest.mark.parametrize(("exc", "expected"), [
    (Transient("fetch failed: Read timed out"), "network"),
    (Transient("retryable HTTP 429 for https://x"), "rate_limit"),
    (Transient("retryable HTTP 503 for https://x"), "network"),
    (Gone("HTTP 404 for https://x"), "gone"),
    (_http_error(403), "blocked"),
    (ValueError("unexpected markup"), "parse"),
])
def test_error_class(exc, expected):
    assert error_class(exc) == expected


@pytest.mark.django_db
def test_repeat_outcomes_extend_and_silences_become_unknown(source):
    t0 = timezone.now() - timedelta(hours=2)
    record = CoverageInterval.record
    record(source, "covered", now=t0)
    record(source, "covered", now=t0 + timedelta(minutes=2))
    record(source, "gap", "network", now=t0 + timedelta(minutes=4))
    record(source, "gap", "network", now=t0 + timedelta(minutes=6))
    record(source, "covered", now=t0 + timedelta(minutes=60))

    rows = list(CoverageInterval.objects.order_by("started_at", "id")
                .values_list("state", "error_class", "started_at", "ended_at"))
    assert [(state, cls) for state, cls, *_ in rows] == [
        ("covered", ""), ("gap", "network"), ("unknown", ""), ("covered", ""),
    ]
    # Contiguous: each interval starts where the previous one ended.
    assert all(rows[i][2] == rows[i - 1][3] for i in range(1, len(rows)))
    assert rows[1][2:] == (t0 + timedelta(minutes=2), t0 + timedelta(minutes=6))


@pytest.mark.django_db
def test_failed_crawl_opens_classified_gap(source):
    with patch("sources.tasks.strategies.fetch", side_effect=_http_error(403)):
        with pytest.raises(requests.HTTPError):
            crawl_source.apply(args=[source.name], throw=True)

    assert CrawlAttempt.objects.get().error_class == "blocked"
    gap = CoverageInterval.objects.get()
    assert (gap.state, gap.error_class) == ("gap", "blocked")


@pytest.mark.django_db
def test_closing_a_gap_queues_one_bounded_backfill(source, django_capture_on_commit_callbacks):
    from sources.extraction import RawArticle
    from sources.tasks import backfill_gap

    started = timezone.now() - timedelta(hours=5)
    CoverageInterval.objects.create(source=source, started_at=started,
                                    ended_at=timezone.now(), state="gap", error_class="network")
    raw = RawArticle(source=source.name, url="https://www.mehrnews.com/news/77",
                     title="تیتر بازیابی‌شده", content="متن کامل " * 40)
    # The new article queues an assessment on commit; never let that reach the provider.
    with patch("sources.tasks.strategies.fetch", return_value=[raw]), \
            patch("sources.tasks.backfill_gap.delay") as queued, \
            patch("inference.tasks.assess_event.delay"), \
            django_capture_on_commit_callbacks(execute=True):
        crawl_source.apply(args=[source.name], throw=True)
        crawl_source.apply(args=[source.name], throw=True)  # still covered: no second run
    queued.assert_called_once_with(source.name, started.date().isoformat())

    archive = [RawArticle(source=source.name, url=f"https://www.mehrnews.com/news/{n}",
                          title=f"تیتر آرشیو {n}", content="متن " * 40) for n in (78, 79)]
    with patch("sources.tasks.strategies.backfill", return_value=iter(archive)), \
            patch("sources.tasks.BACKFILL_MAX_ARTICLES", 1):
        assert backfill_gap.run(source.name, started.date().isoformat())["new"] == 1
