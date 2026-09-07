"""Article-level background work: image download, dedup sweeps, prefilter reapplication."""

from __future__ import annotations

import logging
from datetime import timedelta
from io import BytesIO

import requests
from celery import Task, shared_task
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from core.actions import log_action
from core.errors import Transient
from core.net import BlockedURL, open_checked, read_capped
from sources.extraction import build_session

from .models import ArticleImage, ImageStatus
from .url_health import check_stale_urls as check_stale_urls

GONE_HTTP = {404, 410}

logger = logging.getLogger(__name__)

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
        article_id = kwargs.get("article_id", args[0] if args else None)
        if article_id is None:
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
    article_ids = list(pending.values_list("article_id", flat=True)[:limit])
    for article_id in article_ids:
        download_image.delay(article_id)
    return {"queued": len(article_ids)}


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
