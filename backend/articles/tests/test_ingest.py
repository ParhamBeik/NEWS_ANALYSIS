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
