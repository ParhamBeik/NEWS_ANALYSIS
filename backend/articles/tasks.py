"""Article-level background work: image download, URL health, dedup sweeps, prefilter.

Everything Celery runs for this app lives here, because `celery autodiscover_tasks` imports
`tasks.py` and nothing else. A task defined in a sibling module is registered only if
`tasks.py` happens to import it, and a task that is not registered is a name beat schedules
and no worker answers - silence at 04:30 on a Sunday rather than an error anyone sees.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from io import BytesIO

import requests
from celery import Task, shared_task
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from core.actions import log_action
from core.errors import Transient
from core.net import BlockedURL, open_checked, read_capped
from sources.extraction import build_session

from .models import Article, ArticleImage, ImageStatus, UrlStatus

# 404 and 410 both mean the outlet deleted or moved the story. Counting that is useful;
# retrying it is not.
GONE_HTTP = {404, 410}

logger = logging.getLogger(__name__)

# A CDN that cannot even be resolved from this VPS will not recover inside Celery's
# 5s-retry window. Remember the host so later pictures skip the connect timeout entirely.
# ponytail: 24h TTL; drop the Redis skip if the host starts resolving again.
DEAD_IMAGE_HOST_PREFIX = "newsintel:image-dead-host:"
DEAD_IMAGE_HOST_TTL = 24 * 60 * 60


def _image_host(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).netloc or "").lower()


def image_host_is_dead(host: str) -> bool:
    if not host:
        return False
    try:
        from inference import budget

        return bool(budget.client().get(DEAD_IMAGE_HOST_PREFIX + host))
    except Exception:
        return False


def _remember_dead_image_host(host: str) -> None:
    if not host:
        return
    try:
        from inference import budget

        budget.client().set(DEAD_IMAGE_HOST_PREFIX + host, "1", ex=DEAD_IMAGE_HOST_TTL)
    except Exception:
        logger.warning("could not record dead image host %s", host, exc_info=True)


DISPLAY_MAX = (1200, 1200)
THUMBNAIL_MAX = (400, 400)
MAX_BYTES = 8 * 1024 * 1024
JPEG_QUALITY = 82


def _encode(image: Image.Image, size: tuple[int, int]) -> ContentFile:
    """Downscale in place and re-encode as JPEG.

    Re-encoded rather than stored as fetched: these CDNs serve 1-2MB originals, and the
    feed shows a card thumbnail. Storing the original would spend ~20x the disk to display
    the same 400px image.
    """
    copy = image.copy()
    copy.thumbnail(size, Image.LANCZOS)
    if copy.mode not in ("RGB", "L"):
        copy = copy.convert("RGB")
    buffer = BytesIO()
    copy.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return ContentFile(buffer.getvalue())


class RecordImageFailure(Task):
    """Write a terminal status when `download_image` gives up.

    Every failure the task *handles* already marks the row - GONE for a 404, FAILED for an
    oversized or undecodable body, FAILED for a refused address. The two that escaped were
    the ones that leave by raising: a `Transient` whose retries ran out, and a `Permanent`
    that no handler names (a redirect loop). Those left the row PENDING, which is the same
    state a never-queued image has, so `download_pending_images` could not tell "not tried
    yet" from "tried three times and unreachable" and re-queued the second kind forever.
    Measured on the VPS: 601 rows for one dead CDN, 0% ever stored across four days, three
    20-second connects each, re-queued every hour - about 86% of the crawl pool's capacity
    spent proving the same host was still down, while newer images from reachable hosts
    were never reached at all.

    Celery calls this only when the task has finally failed, so putting it here covers
    every raising path including ones nobody has written yet, which is the property the
    per-handler version did not have.
    """

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        # Positional first: every production caller is `delay(article.pk)`.
        article_id = args[0] if args else kwargs.get("article_id")
        if article_id is None:
            logger.warning(
                "image on_failure missing article_id task_id=%s args=%s kwargs=%s",
                task_id, args, kwargs,
            )
            return
        # `.update()` on PENDING only: one statement that cannot fail on a deleted row, and
        # that will not overwrite a STORED row if a later attempt won the race.
        updated = ArticleImage.objects.filter(
            article_id=article_id, status=ImageStatus.PENDING
        ).update(status=ImageStatus.FAILED, error=f"{type(exc).__name__}: {exc}"[:500])
        if updated:
            log_action("image.failed", "failed", article=article_id, error=str(exc)[:200])


@shared_task(
    base=RecordImageFailure,
    name="articles.tasks.download_image",
    autoretry_for=(Transient,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=2,
)
def download_image(article_id: int) -> dict:
    """Fetch the headline image and store a display copy plus a thumbnail.

    A missing or broken image is never fatal to an article: the story is the product, the
    picture is decoration. Failures are recorded on the row so /ops can show how often a
    source publishes an image it will not serve.
    """
    record = ArticleImage.objects.filter(article_id=article_id).first()
    if record is None or not record.source_url or record.status in {
        ImageStatus.STORED, ImageStatus.GONE,
    }:
        return {"article": article_id, "status": "skipped"}

    session = build_session()
    try:
        # (connect, read), not one number for both. A dead host costs the full connect
        # timeout on all three attempts, and every CDN that actually answers connects in
        # under a third of a second - measured across the twelve hosts in use, the slowest
        # is 0.32s. Five seconds is generous for the handshake and caps what an unreachable
        # host can spend; the read budget stays at 20s because a slow large image is a
        # different thing from a host that is gone.
        response = open_checked(session, record.source_url, timeout=(5, 20), stream=True)
        try:
            if response.status_code in GONE_HTTP:
                record.status = ImageStatus.GONE
                record.error = f"HTTP {response.status_code}"
                record.save(update_fields=["status", "error"])
                log_action(
                    "image.gone", "gone",
                    article=article_id, http_status=response.status_code,
                )
                return {
                    "article": article_id,
                    "status": "gone",
                    "http_status": response.status_code,
                }
            response.raise_for_status()
            payload = read_capped(response, MAX_BYTES)
        finally:
            response.close()
    except BlockedURL as exc:
        # The most directly attacker-controlled fetch in the system: this URL came out of a
        # third party's JSON-LD or og:image tag, and this worker sits on the same network as
        # Postgres and Redis. Recorded like any other bad image rather than retried - the
        # URL will resolve to the same refused address next time.
        record.status, record.error = ImageStatus.FAILED, f"refused: {exc}"
        record.save(update_fields=["status", "error"])
        return {"article": article_id, "status": "blocked"}
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in GONE_HTTP:
            record.status, record.error = ImageStatus.GONE, f"HTTP {status}"
            record.save(update_fields=["status", "error"])
            log_action("image.gone", "gone", article=article_id, http_status=status)
            return {"article": article_id, "status": "gone", "http_status": status}
        if status and status < 500 and status != 429:
            record.status, record.error = ImageStatus.FAILED, f"HTTP {status}: {exc}"
            record.save(update_fields=["status", "error"])
            log_action("image.failed", "failed", article=article_id, http_status=status)
            return {"article": article_id, "status": "failed", "http_status": status}
        raise Transient(f"image fetch failed: {exc}") from exc
    except Transient as exc:
        host = _image_host(record.source_url)
        record.status, record.error = ImageStatus.FAILED, f"{type(exc).__name__}: {exc}"[:500]
        record.save(update_fields=["status", "error"])
        _remember_dead_image_host(host)
        log_action("image.failed", "failed", article=article_id, host=host, error=str(exc)[:200])
        return {"article": article_id, "status": "failed", "host": host}

    if len(payload) > MAX_BYTES:
        record.status, record.error = ImageStatus.FAILED, "image exceeds size limit"
        record.save(update_fields=["status", "error"])
        return {"article": article_id, "status": "too_large"}

    try:
        image = Image.open(BytesIO(payload))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        # A CDN serving an HTML error page under an image URL is common and is not worth
        # retrying - the bytes will be the same next time.
        record.status, record.error = ImageStatus.FAILED, f"not a decodable image: {exc}"
        record.save(update_fields=["status", "error"])
        return {"article": article_id, "status": "undecodable"}

    stem = f"{article_id}"
    record.file.save(f"{stem}.jpg", _encode(image, DISPLAY_MAX), save=False)
    record.thumbnail.save(f"{stem}_thumb.jpg", _encode(image, THUMBNAIL_MAX), save=False)
    record.width, record.height = image.size
    record.status, record.error = ImageStatus.STORED, ""
    record.fetched_at = timezone.now()
    record.save()
    return {"article": article_id, "status": "stored", "size": image.size}


@shared_task(name="articles.tasks.download_pending_images")
def download_pending_images(limit: int = 200) -> dict:
    """Sweep images that were never queued or whose queueing failed.

    The crawl path swallows broker errors so that a queue problem cannot cost us an
    article; this is what makes that safe - the row stays PENDING and gets picked up here
    instead of being lost.
    """
    # Ordered, because `LIMIT` without `ORDER BY` is whatever order Postgres finds cheapest
    # - in practice the same physical rows every hour. With one CDN stuck PENDING that made
    # this sweep pick the identical 200 dead rows 24 times a day and never once reach the
    # 81 live ones behind them. Newest first: this is a news product, and a picture for
    # today's story is worth more than one for a story from four days ago.
    pending = (
        ArticleImage.objects.filter(status=ImageStatus.PENDING)
        .exclude(source_url="")
        .order_by("-article_id")
    )
    rows = list(pending.values_list("article_id", "source_url")[:limit])
    queued = 0
    skipped = 0
    for article_id, source_url in rows:
        host = _image_host(source_url)
        if image_host_is_dead(host):
            ArticleImage.objects.filter(
                article_id=article_id, status=ImageStatus.PENDING
            ).update(
                status=ImageStatus.FAILED,
                error=f"skipped: host {host} recently unreachable",
            )
            skipped += 1
            continue
        download_image.delay(article_id)
        queued += 1
    return {"queued": queued, "skipped_dead_host": skipped}


@shared_task(name="articles.tasks.backfill_dedupe")
def backfill_dedupe(dry_run: bool = True) -> dict:
    """Sweep recent articles for near-duplicates missed at ingest time.

    The previous full-corpus walk never finished inside the worker time limit, so
    duplicates accumulated. One bounded batch per night, checkpointed in Redis, walks
    the backlog across nights instead of dying with nothing committed.
    """
    from inference import budget

    from . import dedupe

    cursor_key = "newsintel:dedupe:after_id"
    after_id = int(budget.client().get(cursor_key) or 0)
    since = timezone.now() - timedelta(days=7) if after_id == 0 else None
    merged = dedupe.backfill(
        dry_run=dry_run,
        since=since,
        after_id=after_id,
        limit=500,
        time_budget_s=120,
    )
    if not dry_run:
        if merged.exhausted:
            budget.client().set(cursor_key, 0)
        else:
            budget.client().set(cursor_key, merged.last_id)
    log_action(
        "dedupe.backfill",
        "done",
        pairs=len(merged),
        scanned=merged.scanned,
        last_id=merged.last_id,
        exhausted=merged.exhausted,
        dry_run=dry_run,
    )
    return {
        "pairs": len(merged),
        "dry_run": dry_run,
        "scanned": merged.scanned,
        "last_id": merged.last_id,
        "exhausted": merged.exhausted,
        "timed_out": merged.timed_out,
    }


@shared_task(name="articles.tasks.reapply_prefilter")
def reapply_prefilter() -> dict:
    """Re-evaluate every article against the current prefilter rules. Run after editing
    them, so disabling a rule actually releases the articles it was holding back."""
    from sources import prefilter

    return prefilter.reapply()


# ------------------------------------------------------------------------------ url health


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
        if status in GONE_HTTP:
            note_gone(article.url, status)
            return "gone"
        return "transient"
    if status in GONE_HTTP:
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
