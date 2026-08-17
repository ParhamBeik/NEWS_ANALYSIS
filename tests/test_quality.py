"""Quality gates: what must never reach a paid inference call."""

from datetime import datetime, timedelta, timezone

import pytest

from news_intel import quality, sources


def article(**overrides):
    base = dict(
        source="khabarfoori",
        url="https://example.test/1",
        title="حمله موشکی به تاسیسات نفتی کشور",
        lead="جزئیات بیشتر از این حادثه",
        content="متن کامل خبر با جزئیات فراوان",
        published_at="2026-08-16T10:00:00+03:30",
    )
    base.update(overrides)
    return sources.RawArticle(**base)


class TestAccepted:
    def test_normal_article_passes(self):
        assert quality.check(article()).ok

    def test_empty_body_passes_when_title_and_lead_carry_evidence(self):
        """Photo posts genuinely have no body. Title plus lead is enough to classify,
        so rejecting them would drop real stories."""
        assert quality.check(article(content="")).ok

    def test_missing_date_is_allowed(self):
        assert quality.check(article(published_at=None)).ok


class TestRejected:
    def test_missing_title(self):
        verdict = quality.check(article(title=""))
        assert not verdict.ok and verdict.reason == "missing_title"

    def test_short_title(self):
        verdict = quality.check(article(title="خبر"))
        assert not verdict.ok and verdict.reason == "title_too_short"

    def test_no_usable_text_anywhere(self):
        verdict = quality.check(article(title="خبر کوتاه ی", lead="", content=""))
        assert not verdict.ok and verdict.reason == "insufficient_text"

    def test_future_date_is_rejected(self):
        """A future timestamp is a misparsed date, and a wrong date silently breaks
        dedup's time window and the workbook's daily grouping."""
        ahead = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        verdict = quality.check(article(published_at=ahead))
        assert not verdict.ok and verdict.reason == "published_in_future"

    def test_small_clock_skew_is_tolerated(self):
        soon = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        assert quality.check(article(published_at=soon)).ok

    @pytest.mark.parametrize("url", ["", "not-a-url", "ftp://x.test/a", "javascript:alert(1)"])
    def test_invalid_urls(self, url):
        verdict = quality.check(article(url=url))
        assert not verdict.ok and verdict.reason == "invalid_url"

    def test_unparseable_date_does_not_crash(self):
        assert quality.check(article(published_at="پنجشنبه")).ok


class TestPartition:
    def test_splits_and_reports_reasons(self):
        good = article()
        bad = article(url="https://example.test/2", title="")
        accepted, rejected = quality.partition([good, bad])
        assert accepted == [good]
        assert rejected == [(bad, "missing_title")]

    def test_empty_input(self):
        assert quality.partition([]) == ([], [])


class TestVerdictErgonomics:
    def test_verdict_is_truthy(self):
        assert quality.check(article())
        assert not quality.check(article(title=""))
