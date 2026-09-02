"""Crawl tasks.

Retry lives HERE and only here. The strategies and the HTTP helper raise once and return;
a retry loop inside the provider or the fetcher would nest inside Celery's own retry and
compound - three attempts inside three attempts is nine requests for one logical fetch,
with neither layer aware of the other.

One source per task, never all sources in one: a single site being slow or down must not
stop the others, and marking that source degraded while the cycle continues is the whole
point of the health field.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings

from articles.ingest import upsert
from articles.models import ImageStatus
from core.errors import Permanent, Transient

from . import strategies
from .extraction import build_session
from .models import Source

logger = logging.getLogger(__name__)


def _queue_image(article) -> int:
    """Fire-and-forget image download. Returns 1 if one was queued.

    Structurally unable to fail the crawl. The story is the product and the picture is
    decoration, so a CDN timing out must not cost us the article - and it did: a single
    `Read timed out` from cdn.mashreghnews.ir propagated out of an eagerly-executed
    subtask and retried an entire five-article Shahrekhabar crawl.

    Broker failures are swallowed for the same reason. An unqueued image leaves the row
    PENDING, which `download_pending_images` sweeps up later; a raised exception would
    lose articles already extracted.
    """
    image = getattr(article, "image", None)
    if image is None or not image.source_url or image.status == ImageStatus.STORED:
        return 0
    from articles.tasks import download_image

    try:
        download_image.delay(article.pk)
    except Exception:
        logger.warning("could not queue image for article %s", article.pk, exc_info=True)
        return 0
    return 1


@shared_task(
    name="sources.crawl_source",
    autoretry_for=(Transient,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def crawl_source(source_name: str, limit: int | None = None, run_id: str = "") -> dict:
    """Fetch one source and store what it returns.

    `Permanent` is deliberately NOT in autoretry_for: a feed that stopped being XML or a
    strategy that no longer exists will fail identically on every attempt, and retrying it
    spends the budget proving that.
    """
    source = Source.objects.filter(name=source_name, enabled=True).first()
    if source is None:
        raise Permanent(f"no enabled source named {source_name!r}")

    limit = limit or settings.NEWS_CRAWL_LIMIT_PER_SOURCE
    session = build_session()
    try:
        raw_articles = strategies.fetch(source, session, limit=limit)
    except Exception as exc:
        source.mark_degraded(str(exc))
        raise

    stats = {"source": source_name, "fetched": 0, "new": 0, "duplicate": 0, "rejected": 0,
             "prefiltered": 0, "images_queued": 0}
    for raw in raw_articles:
        stats["fetched"] += 1
        article, created = upsert(raw, source, run_id)
        if not created:
            continue
        stats["new"] += 1
        if article.quality_flag:
            stats["rejected"] += 1
        elif article.duplicate_of_id is not None:
            stats["duplicate"] += 1
        elif article.prefilter_reason:
            stats["prefiltered"] += 1
        stats["images_queued"] += _queue_image(article)

    source.mark_healthy()
    logger.info("crawl %s: %s", source_name, stats)
    return stats


@shared_task(name="sources.crawl_all")
def crawl_all(limit: int | None = None) -> dict:
    """Fan out one task per enabled source. Returns what was dispatched, not what was
    fetched - the per-source results land in their own task records."""
    names = list(Source.objects.filter(enabled=True).values_list("name", flat=True))
    for name in names:
        crawl_source.delay(name, limit)
    return {"dispatched": names}


@shared_task(name="sources.canary")
def canary() -> list[dict]:
    """Is each source still alive, and is its parser still finding articles?

    A source returning HTTP 200 with zero parsed articles is the failure mode that matters
    - a redesign does not usually break the connection, it breaks the selector - so an
    empty result is treated as degraded rather than as a quiet success.
    """
    session = build_session()
    results = []
    for source in Source.objects.filter(enabled=True):
        try:
            found = strategies.fetch(source, session, limit=3)
        except Exception as exc:
            source.mark_degraded(str(exc))
            results.append({"source": source.name, "ok": False, "error": str(exc)[:200]})
            continue
        if not found:
            source.mark_degraded("fetch succeeded but parsed zero articles")
            results.append({"source": source.name, "ok": False, "error": "zero articles parsed"})
            continue
        source.mark_healthy()
        results.append(
            {
                "source": source.name,
                "ok": True,
                "articles": len(found),
                "tiers": sorted({article.extraction_tier for article in found}),
                "with_image": sum(1 for article in found if article.image_url),
            }
        )
    return results
