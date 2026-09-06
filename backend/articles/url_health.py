"""Record permanently dead article URLs instead of fetching them forever.

A 404 is information: the outlet deleted or moved the story. Counting those is useful;
retrying them is not.
"""

from __future__ import annotations

from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from core.actions import log_action
from core.net import BlockedURL, open_checked

from .models import Article, UrlStatus

GONE_STATUSES = {404, 410}


def note_gone(url: str, http_status: int) -> bool:
    """Mark a stored article gone. Returns True if a row was updated."""
    now = timezone.now()
    updated = Article.objects.filter(url=url).exclude(url_status=UrlStatus.GONE).update(
        url_status=UrlStatus.GONE,
        gone_at=now,
        gone_http_status=http_status,
    )
    log_action("url.gone", "gone", url=url[:200], http_status=http_status, updated=updated)
    return bool(updated)


def _check_one(article: Article) -> str:
    session = requests.Session()
    session.headers.update({"User-Agent": settings.NEWS_USER_AGENT})
    try:
        response = open_checked(session, article.url, timeout=15, stream=True)
        try:
            status = response.status_code
        finally:
            response.close()
    except BlockedURL:
        return "blocked"
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status in GONE_STATUSES:
            note_gone(article.url, status)
            return "gone"
        return "transient"
    if status in GONE_STATUSES:
        note_gone(article.url, status)
        return "gone"
    return "live"


MAX_STALE_CHECK = 200


@shared_task(name="articles.tasks.check_stale_urls")
def check_stale_urls(limit: int = 100) -> dict:
    """HEAD/GET articles that have fallen off the listing. 404 becomes GONE, once."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, MAX_STALE_CHECK))
    cutoff = timezone.now() - timedelta(days=7)
    stale = (
        Article.objects.filter(url_status=UrlStatus.LIVE, fetched_at__lt=cutoff)
        .order_by("fetched_at")
        [:limit]
    )
    counts = {"checked": 0, "gone": 0, "live": 0, "transient": 0, "blocked": 0}
    for article in stale:
        counts["checked"] += 1
        outcome = _check_one(article)
        counts[outcome] = counts.get(outcome, 0) + 1
    log_action("url.health", "done", **counts)
    return counts
