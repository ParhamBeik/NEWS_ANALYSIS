"""The quality gate and the ingest path.

The gate runs before anything is paid for, so its job is to stop text the extractor
mangled. It returns a REASON, not a bool, because a gate that fires often is a broken
parser announcing itself and /ops groups the failures by cause.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from articles.ingest import MIN_EVIDENCE_CHARS, quality_reason, upsert
from articles.models import ImageStatus
from sources.extraction import RawArticle

pytestmark = pytest.mark.django_db


def raw(**overrides) -> RawArticle:
    fields = {
        "source": "mehr",
        "url": "https://www.mehrnews.com/news/1",
        "title": "یک تیتر خبری با طول کافی",
        "lead": "خلاصه‌ای از خبر",
        "content": "متن کامل خبر.",
        "published_at": timezone.now().isoformat(),
    }
    fields.update(overrides)
    return RawArticle(**fields)


class TestQualityGate:
    def test_a_good_article_passes(self):
        assert quality_reason(raw()) == ""

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            ({"title": ""}, "missing_title"),
            ({"title": "کوتاه"}, "title_too_short"),
            ({"url": "javascript:alert(1)"}, "invalid_url"),
            ({"url": ""}, "invalid_url"),
        ],
    )
    def test_reasons(self, overrides, expected):
        assert quality_reason(raw(**overrides)) == expected

    def test_future_timestamps_are_rejected(self):
        """A future date means a misparsed date, which silently breaks dedup's time window
        and the workbook's daily grouping."""
        future = (timezone.now() + timedelta(days=2)).isoformat()
        assert quality_reason(raw(published_at=future)) == "published_in_future"

    def test_a_small_clock_skew_is_tolerated(self):
        near = (timezone.now() + timedelta(hours=1)).isoformat()
        assert quality_reason(raw(published_at=near)) == ""

    def test_feed_only_articles_clear_the_evidence_bar(self):
        """IRNA and ISNA arrive with a ~220 character description and no body. They are
        thin, but they are real articles and must not be gated out."""
        article = raw(content="", lead="x" * 220)
        assert len(article.title) + len(article.lead) >= MIN_EVIDENCE_CHARS
        assert quality_reason(article) == ""

    def test_an_empty_extraction_is_rejected(self):
        assert quality_reason(raw(title="عنوان کوتاه ولی", lead="", content="")) == (
            "insufficient_text"
        )


class TestUpsert:
    def test_creates_an_article_with_derived_date_fields(self, source):
        article, created = upsert(raw(), source, run_id="r1")
        assert created
        assert article.published_at is not None
        assert article.published_at_jalali.count("-") == 2, "Jalali date is stored, not derived"
        assert len(article.published_time) == 5

    def test_reingesting_the_same_url_touches_rather_than_duplicates(self, source):
        first, created_first = upsert(raw(), source, run_id="r1")
        second, created_second = upsert(raw(content="متن به‌روزشده"), source, run_id="r2")
        assert created_first and not created_second
        assert first.pk == second.pk

    def test_a_celery_task_id_fits_as_the_run_id(self, source):
        """Scheduled crawls pass the 36-character Celery task id; a 32-char column stopped
        every insert in production."""
        task_id = "4b8d3c1e-9f0a-4c6e-8a1b-2d3e4f5a6b7c"
        article, _ = upsert(raw(), source, run_id=task_id)
        again, _ = upsert(raw(), source, run_id=task_id)
        assert article.first_seen_run == again.last_seen_run == task_id

    def test_native_category_is_lowercased(self, source):
        """Mehr emits CamelCase, IRNA lowercase, ISNA numeric ids. Normalising at write
        time is what lets one prefilter lookup serve all three."""
        article, _ = upsert(raw(native_category="KhorasanJonoobi"), source)
        assert article.native_category == "khorasanjonoobi"

    def test_quality_failures_are_stored_not_discarded(self, source):
        """A rejected article is still kept: /ops needs the count and the cause, and a
        parser regression is invisible if the evidence is thrown away."""
        article, created = upsert(raw(title="کوتاه"), source)
        assert created and article.quality_flag == "title_too_short"

    def test_an_image_url_creates_a_pending_download(self, source):
        article, _ = upsert(raw(image_url="https://cdn.example.com/a.jpg"), source)
        assert article.image.status == ImageStatus.PENDING

    def test_no_image_is_recorded_as_absent_not_pending(self, source):
        """Distinguishing 'this source published no photo' from 'we have not fetched it
        yet' is what stops the download queue retrying nothing forever."""
        article, _ = upsert(raw(), source)
        assert article.image.status == ImageStatus.ABSENT

    def test_undated_articles_are_marked_uncertain(self, source):
        article, _ = upsert(raw(published_at=None), source)
        assert article.date_uncertain and article.published_at is None

    def test_keywords_are_capped(self, source):
        article, _ = upsert(raw(keywords=[f"k{i}" for i in range(30)]), source)
        assert len(article.keywords) == 12

    def test_a_404_marks_the_stored_url_gone(self, source):
        """Unit: deletion is a stored fact, so the next crawl does not treat it as live."""
        from articles.models import UrlStatus
        from articles.tasks import note_gone

        article, _ = upsert(raw(), source)
        assert note_gone(article.url, 404) is True
        article.refresh_from_db()
        assert article.url_status == UrlStatus.GONE
        assert article.gone_http_status == 404

    def test_a_first_seen_404_is_stored_gone(self, source):
        """Saba keeps the feed row after a detail 404. The deletion must be stored, not live."""
        from articles.models import UrlStatus

        article, created = upsert(raw(gone_http_status=404, extraction_tier="feed"), source)
        assert created
        assert article.url_status == UrlStatus.GONE
        assert article.gone_http_status == 404

    def test_a_listing_row_does_not_revive_a_gone_url(self, source):
        """Saba still upserts the feed row after a detail 404. That is not a resurrection."""
        from articles.models import ExtractionTier, UrlStatus
        from articles.tasks import note_gone

        article, _ = upsert(raw(), source)
        note_gone(article.url, 404)
        upsert(raw(extraction_tier=ExtractionTier.LISTING, content=""), source, run_id="r2")
        article.refresh_from_db()
        assert article.url_status == UrlStatus.GONE
        assert article.gone_http_status == 404

    def test_a_real_page_revives_a_gone_url(self, source):
        from articles.models import ExtractionTier, UrlStatus
        from articles.tasks import note_gone

        article, _ = upsert(raw(), source)
        note_gone(article.url, 404)
        upsert(raw(extraction_tier=ExtractionTier.CSS, content="متن کامل برگشته."), source)
        article.refresh_from_db()
        assert article.url_status == UrlStatus.LIVE

    def test_feed_correction_keeps_prior_evidence(self, source):
        from articles.models import ArticleRevision, EventRevision, NewsEvent

        first, _ = upsert(raw(content="", extraction_tier="feed", lead="Original summary text."), source)
        event = first.news_events.get()
        NewsEvent.objects.filter(pk=event.pk).update(brief_fa="خلاصهٔ قدیمی")
        upsert(raw(content="", extraction_tier="feed", lead="Corrected summary text."), source)
        first.refresh_from_db()
        assert first.lead == "Corrected summary text."
        assert ArticleRevision.objects.get(article=first).lead == "Original summary text."
        assert first.news_events.get().status == NewsEvent.Status.CORRECTED
        event.refresh_from_db()
        assert event.brief_fa == ""
        assert EventRevision.objects.get(event=event).brief_fa == "خلاصهٔ قدیمی"

    def test_a_correction_to_a_gated_article_buys_no_assessment(
        self, source, django_capture_on_commit_callbacks
    ):
        from unittest.mock import patch

        from articles.models import ExtractionTier

        with patch("inference.tasks.assess_event.delay") as queued, \
                django_capture_on_commit_callbacks(execute=True):
            upsert(raw(title="کوتاه"), source)
            upsert(raw(title="کوتاه", extraction_tier=ExtractionTier.CSS, content="متن تازه."), source)
            queued.assert_not_called()
            # A correction that fixes the text clears the flag and is assessed.
            fixed, _ = upsert(raw(extraction_tier=ExtractionTier.CSS, content="متن کامل."), source)
        assert fixed.quality_flag == ""
        queued.assert_called_once()
