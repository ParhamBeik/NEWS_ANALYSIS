"""Turning a parsed RawArticle into a stored row: quality gate, upsert, dedup, prefilter.

The quality gate runs BEFORE anything is paid for. Every article that reaches the
classifier costs a real call, so anything the extractor mangled is stopped here. It
returns a reason string rather than a bool, because a gate that fires often is a broken
parser announcing itself and /ops groups the failures by cause.
"""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.text import clean, jalali_str, parse_iso, to_jalali
from sources import prefilter
from sources.extraction import RawArticle

from . import dedupe
from .models import Article, ArticleImage, ImageStatus

MIN_TITLE_CHARS = 10
# Title plus lead is enough to judge a photo post; a full body is not required. IRNA and
# ISNA arrive feed-only with ~220 characters and must still clear this.
MIN_EVIDENCE_CHARS = 40
FUTURE_TOLERANCE = timedelta(hours=6)


def quality_reason(raw: RawArticle, *, now=None) -> str:
    """Why this article is not worth an inference call, or '' if it is."""
    title = clean(raw.title)
    if not title:
        return "missing_title"
    if len(title) < MIN_TITLE_CHARS:
        return "title_too_short"
    evidence = len(title) + len(clean(raw.lead)) + len(clean(raw.content))
    if evidence < MIN_EVIDENCE_CHARS:
        return "insufficient_text"
    published = parse_iso(raw.published_at)
    if published is not None:
        if timezone.is_naive(published):
            published = published.replace(tzinfo=ZoneInfo("UTC"))
        # A future timestamp means a misparsed date, which silently breaks dedup's time
        # window and the workbook's daily grouping.
        if published > (now or timezone.now()) + FUTURE_TOLERANCE:
            return "published_in_future"
    if not raw.url or not raw.url.startswith(("http://", "https://")):
        return "invalid_url"
    return ""


def published_fields(value: str | None) -> tuple[object, str, str]:
    """(aware datetime | None, jalali 'YYYY-MM-DD', 'HH:MM') in Tehran local time.

    Storage stays UTC; the Jalali date and clock time are Tehran-local because that is what
    the workbook groups by and what an analyst reads. Deriving them at write time means the
    gap-detection query can hit an index instead of converting a million rows on read.
    """
    moment = parse_iso(value)
    if moment is None:
        return None, "", ""
    if timezone.is_naive(moment):
        moment = moment.replace(tzinfo=ZoneInfo("UTC"))
    local = moment.astimezone(ZoneInfo(settings.TEHRAN_TZ))
    return moment, jalali_str(to_jalali(local)), local.strftime("%H:%M")


@transaction.atomic
def upsert(raw: RawArticle, source, run_id: str = "") -> tuple[Article, bool]:
    """Store or touch an article. Returns (article, newly created).

    Insert first, then resolve duplicates: dedup compares against stored rows, and linking
    may decide this newer copy is the better canonical and demote the existing one - in
    which case THIS row is not the duplicate and does need inference.
    """
    existing = Article.objects.filter(url=raw.url).first()
    if existing is not None:
        Article.objects.filter(pk=existing.pk).update(
            last_seen_run=run_id, fetched_at=timezone.now()
        )
        return existing, False

    published_at, jalali, clock = published_fields(raw.published_at)
    article = Article.objects.create(
        url=raw.url,
        source=source,
        original_outlet=clean(raw.original_outlet or ""),
        original_title=clean(raw.title),
        lead=clean(raw.lead),
        content=raw.content,
        content_hash=raw.content_hash,
        published_at=published_at,
        published_at_jalali=jalali,
        published_time=clock,
        date_uncertain=raw.date_uncertain or published_at is None,
        native_category=(raw.native_category or "").lower()[:64],
        keywords=raw.keywords[:12],
        extraction_tier=raw.extraction_tier,
        quality_flag=quality_reason(raw),
        prefilter_reason=prefilter.reason_for(source.name, raw.native_category),
        fetched_at=timezone.now(),
        first_seen_run=run_id,
        last_seen_run=run_id,
    )
    dedupe.resolve(article)

    if raw.image_url:
        ArticleImage.objects.get_or_create(
            article=article,
            defaults={"source_url": raw.image_url, "status": ImageStatus.PENDING},
        )
    else:
        ArticleImage.objects.get_or_create(
            article=article, defaults={"source_url": "", "status": ImageStatus.ABSENT}
        )
    return article, True
