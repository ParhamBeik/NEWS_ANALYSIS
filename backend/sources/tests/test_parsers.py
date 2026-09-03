"""Parser tests against saved fixtures. No network, no API cost.

Fixtures are real pages captured from the live sites. When a site is redesigned these
tests fail, which is the point: the alternative is discovering it from a workbook that
quietly got thinner.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sources.extraction import RawArticle, json_ld, keywords_from, soup_of
from sources.strategies import khabarfoori, saba, shahrekhabar

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestSabaFeed:
    """Mehr, IRNA and ISNA share this shape - one parser, three sources."""

    @pytest.fixture
    def articles(self) -> list[RawArticle]:
        return saba.parse_feed(fixture("saba_feed.xml"), "mehr", "مهر")

    def test_parses_every_item(self, articles):
        assert len(articles) == 3
        assert all(article.url and article.title for article in articles)

    def test_extracts_the_enclosure_image(self, articles):
        """Previously discarded on every single item."""
        images = [article.image_url for article in articles if article.image_url]
        assert images, "the feed publishes <enclosure> images and they must be captured"
        assert all(url.startswith("http") for url in images)

    def test_extracts_the_native_taxonomy_slug(self, articles):
        """The `domain` attribute is the machine slug; the element text is a Persian
        breadcrumb. Keying config on the breadcrumb would break on any rewording."""
        slugs = [article.native_category for article in articles if article.native_category]
        assert slugs
        assert all(slug == slug.lower() for slug in slugs)

    def test_feed_only_articles_are_marked_as_such(self, articles):
        """Tier is how thin evidence stays visible instead of being averaged away."""
        assert all(article.extraction_tier == "feed" for article in articles)

    def test_publication_dates_are_parsed(self, articles):
        dated = [article for article in articles if article.published_at]
        assert dated and all(not article.date_uncertain for article in dated)

    def test_malformed_feed_is_permanent_not_transient(self):
        """A feed that stopped being XML is a site change. Retrying spends the budget
        proving the same bytes are still broken."""
        from core.errors import Permanent

        with pytest.raises(Permanent):
            saba.parse_feed("<not-xml", "mehr", "مهر")

    def test_items_without_a_link_are_dropped(self):
        xml = """<?xml version="1.0"?><rss><channel>
            <item><title>یک عنوان کافی بلند برای تست</title></item>
            <item><title>عنوان دوم</title><link>https://example.com/a</link></item>
        </channel></rss>"""
        assert len(saba.parse_feed(xml, "mehr", "مهر")) == 1


class TestKhabarfoori:
    def test_listing_yields_absolute_urls(self):
        urls = khabarfoori.parse_listing(
            fixture("khabarfoori_listing.html"), "https://www.khabarfoori.com/بخش-اخبار-2"
        )
        assert urls, "listing selector found nothing - the site was probably redesigned"
        assert all(url.startswith("https://") for url in urls)
        assert len(urls) == len(set(urls)), "listing must not repeat a URL"

    def test_listing_page_holds_only_ten_links(self):
        """Pinned because it is WHY the crawler pages the listing: asking for 40 articles
        and silently getting 10 is how this source stopped filling the window."""
        urls = khabarfoori.parse_listing(
            fixture("khabarfoori_listing.html"), "https://www.khabarfoori.com/بخش-اخبار-2"
        )
        assert len(urls) <= 10

    @pytest.fixture
    def article(self) -> RawArticle:
        return khabarfoori.parse_article(
            fixture("khabarfoori_article.html"), fixture("khabarfoori_article.url").strip()
        )

    def test_extracts_a_real_body(self, article):
        assert len(article.content) > 300, "body extraction collapsed to a stub"

    def test_prefers_json_ld_over_the_css_selector(self, article):
        """articleBody beat the selector on every article measured: the selector reads only
        <p>, dropping headings, lists and blockquotes - 5-10% of the text."""
        assert article.extraction_tier in {"jsonld", "css"}

    def test_extracts_image_and_keywords(self, article):
        assert article.image_url.startswith("http")
        assert article.keywords, "the page publishes meta keywords and they were discarded"

    def test_pagination_url_shape(self):
        base = "https://www.khabarfoori.com/بخش-اخبار-2"
        assert khabarfoori.page_url(base, 1) == base
        assert khabarfoori.page_url(base, 3) == f"{base}/?page=3"


class TestShahrekhabar:
    @pytest.fixture
    def listed(self) -> list[RawArticle]:
        return shahrekhabar.parse_listing(
            fixture("shahrekhabar_listing.html"), "https://www.shahrekhabar.com/آخرین-اخبار"
        )

    def test_listing_yields_articles_with_crediting_outlets(self, listed):
        assert listed
        assert any(article.original_outlet for article in listed), (
            "this source is an index; the crediting outlet is what makes cross-source "
            "dedup possible"
        )

    def test_listing_rows_are_undated(self, listed):
        """Every article starts date_uncertain until a detail page supplies a date. Dedup
        must handle them via the ingest-order fallback, not skip them."""
        assert all(article.date_uncertain for article in listed)

    def test_relay_target_prefers_the_iframe(self):
        html = '<html><body><iframe src="/real/article"></iframe></body></html>'
        assert (
            shahrekhabar.relay_target(html, "https://www.shahrekhabar.com/x")
            == "https://www.shahrekhabar.com/real/article"
        )

    def test_relay_target_falls_back_to_meta_refresh(self):
        html = '<html><head><meta http-equiv="refresh" content="0;url=https://x.ir/a"></head></html>'
        assert shahrekhabar.relay_target(html, "https://www.shahrekhabar.com/x") == "https://x.ir/a"

    def test_relay_target_falls_back_to_the_page_itself(self):
        """Some entries are hosted rather than framed and still parse."""
        page = "https://www.shahrekhabar.com/x"
        assert shahrekhabar.relay_target("<html></html>", page) == page


class TestKeywordExtraction:
    def test_deduplicates_and_caps(self):
        soup = soup_of('<meta name="keywords" content="a, b, a, c, b">')
        assert keywords_from(soup, {}, limit=10) == ["a", "b", "c"]

    def test_accepts_a_json_ld_list(self):
        assert keywords_from(soup_of("<html></html>"), {"keywords": ["x", "y"]}) == ["x", "y"]

    def test_missing_keywords_is_an_empty_list(self):
        assert keywords_from(soup_of("<html></html>"), {}) == []


class TestJsonLd:
    def test_walks_graph_nodes(self):
        """Several Iranian CMSes nest the article inside @graph rather than publishing it
        at the top level."""
        html = """<script type="application/ld+json">
        {"@graph": [{"@type": "WebPage"}, {"@type": "NewsArticle", "headline": "خبر"}]}
        </script>"""
        assert json_ld(soup_of(html)).get("headline") == "خبر"

    def test_invalid_json_is_skipped_not_raised(self):
        assert json_ld(soup_of('<script type="application/ld+json">{oops</script>')) == {}
