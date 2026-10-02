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
