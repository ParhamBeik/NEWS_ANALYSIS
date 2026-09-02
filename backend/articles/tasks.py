"""Article-level background work: image download, dedup sweeps, prefilter reapplication."""

from __future__ import annotations

import logging
from io import BytesIO

import requests
from celery import shared_task
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from core.errors import Transient
from sources.extraction import build_session

from .models import ArticleImage, ImageStatus

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


@shared_task(
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
    if record is None or not record.source_url or record.status == ImageStatus.STORED:
        return {"article": article_id, "status": "skipped"}

    session = build_session()
    try:
        response = session.get(record.source_url, timeout=20, stream=True)
        response.raise_for_status()
        payload = response.content[: MAX_BYTES + 1]
    except requests.RequestException as exc:
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
    pending = ArticleImage.objects.filter(status=ImageStatus.PENDING).exclude(source_url="")
    article_ids = list(pending.values_list("article_id", flat=True)[:limit])
    for article_id in article_ids:
        download_image.delay(article_id)
    return {"queued": len(article_ids)}


@shared_task(name="articles.tasks.backfill_dedupe")
def backfill_dedupe(dry_run: bool = True) -> dict:
    """Sweep stored articles for near-duplicates missed at ingest time."""
    from . import dedupe

    merged = dedupe.backfill(dry_run=dry_run)
    return {"pairs": len(merged), "dry_run": dry_run}


@shared_task(name="articles.tasks.reapply_prefilter")
def reapply_prefilter() -> dict:
    """Re-evaluate every article against the current prefilter rules. Run after editing
    them, so disabling a rule actually releases the articles it was holding back."""
    from sources import prefilter

    return prefilter.reapply()
