"""Source extraction, fetch dispatch, backfill pagination, and the pre-inference gate.

The extraction cases are regressions found by auditing live fetches; each carries the
measurement that exposed it.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
import requests

from news_intel import pipeline, sources


class Response:
    def __init__(self, text, status=200):
        self.text, self.status = text, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"HTTP {self.status}")


class Session:
    """Answers only the URLs it was given - an unexpected fetch raises KeyError, which is
    how the pagination tests prove a page was never requested."""

    def __init__(self, responses):
        self.responses = responses

    def get(self, url, **_):
        return self.responses[url]


def khabarfoori_page(*, paragraphs=(), article_body="", headline="عنوان کامل خبر برای تست",
                     editor_id="main_ck_editor", published="2026-08-16T10:00:00+03:30"):
    ld = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": headline,
          "description": "لید خبر", "articleBody": article_body, "datePublished": published}
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return f"""<html><head>
    <script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
    </head><body><h1 class="title">{headline}</h1>
    <div id="{editor_id}">{body}</div></body></html>"""


# ------------------------------------------------------------------------- parsing


def test_khabarfoori_listing_and_article_are_structured_first():
    listing = """<ul class="box container"><li><div class="detail"><h2 class="title">
    <a href="/news/1">خبر نمونه</a></h2></div></li></ul>"""
    assert sources.parse_khabarfoori_listing(listing, "https://site.test") == \
        ["https://site.test/news/1"]

    html = """
    <script type="application/ld+json">{"@type":"NewsArticle","headline":"عنوان ساختاریافته",
    "description":"لید ساختاریافته","datePublished":"2026-08-16T10:00:00+03:30"}</script>
    <div id="main_ck_editor"><p>بند اول خبر با متن کافی.</p><p>بند دوم خبر.</p></div>
    <div class="source_news"><span class="source_title">منبع:</span><span>ایسنا</span></div>
    """
    article = sources.parse_khabarfoori_article(html, "https://site.test/news/1")
    assert article.title == "عنوان ساختاریافته"
    assert article.original_outlet == "ایسنا"
    assert article.content == "بند اول خبر با متن کافی.\nبند دوم خبر."
    assert article.date_uncertain is False


def test_mehr_rss_and_shahrekhabar_listing_normalize_to_raw_articles():
    feed = """<rss><channel><item><title>خبر مهر</title><link>https://mehr.test/1</link>
    <description>خلاصه</description><pubDate>Sun, 16 Aug 2026 10:00:00 +0330</pubDate>
    </item></channel></rss>"""
    listing = """<ul class="news-list-items"><li><a href="/a">خبر شهر</a>
    <span class="refrence minw88">مهر</span></li></ul>"""
    mehr = sources.parse_mehr_feed(feed)
    shahr = sources.parse_shahrekhabar_listing(listing, "https://shahr.test")
    assert mehr[0].source == "mehr" and mehr[0].published_at
    assert shahr[0].source == "shahrekhabar" and shahr[0].original_outlet == "مهر"


def test_shahrekhabar_relay_target_prefers_iframe():
    assert sources.shahrekhabar_target(
        '<iframe src="https://origin.test/a"></iframe>', "https://relay.test/a"
    ) == "https://origin.test/a"


class TestJsonLdBodyPreferred:
    """The CSS selector reads only <p>, so headings, list items and blockquotes were
    dropped. JSON-LD articleBody was longer on 10 of 10 live khabarfoori articles."""

    def test_jsonld_wins_when_longer(self):
        html = khabarfoori_page(paragraphs=["کوتاه"], article_body="متن کامل و طولانی تر از پاراگراف ها")
        parsed = sources.parse_khabarfoori_article(html, "https://k.test/1")
        assert parsed.content == "متن کامل و طولانی تر از پاراگراف ها"
        assert parsed.extraction_tier == "jsonld"

    def test_css_is_the_fallback_when_jsonld_is_empty(self):
        html = khabarfoori_page(paragraphs=["پاراگراف اول", "پاراگراف دوم"])
        parsed = sources.parse_khabarfoori_article(html, "https://k.test/1")
        assert "پاراگراف اول" in parsed.content and "پاراگراف دوم" in parsed.content
        assert parsed.extraction_tier == "css"

    def test_a_redesign_shows_as_an_empty_body_not_silent_truncation(self):
        broken = khabarfoori_page(editor_id="renamed_by_redesign")
        assert sources.parse_khabarfoori_article(broken, "https://k.test/1").content == ""

    def test_generic_parser_also_prefers_jsonld(self):
        html = khabarfoori_page(paragraphs=["کوتاه"], article_body="متن کامل و بسیار طولانی تر")
        parsed = sources.parse_generic_article(html, "mehr", "https://m.test/1")
        assert parsed.content == "متن کامل و بسیار طولانی تر"
        assert parsed.extraction_tier == "jsonld"


# ------------------------------------------------------------------------ dispatch


def test_shahrekhabar_skips_stale_relays_until_the_limit():
    listing = """<ul class="news-list-items">
    <li><a href="/stale">stale</a></li><li><a href="/live">live</a></li></ul>"""
    spec = sources.SourceSpec("shahrekhabar", 2, "listing_relay", "https://shahr.test/list")
    session = Session({
        spec.url: Response(listing),
        "https://shahr.test/stale": Response("", 404),
        "https://shahr.test/live": Response(
            '<h1>live title</h1><p>This is enough article content for extraction.</p>'
        ),
    })
    assert [a.title for a in sources.fetch(spec, session, limit=1)] == ["live title"]


def test_fetch_dispatches_by_strategy_not_by_source_name():
    """A 4th source reusing an existing strategy needs no change to fetch() itself."""
    sources._STRATEGIES["test-strategy"] = lambda spec, session, response, limit: [
        sources.RawArticle(source=spec.name, url=spec.url, title="from registry")
    ]
    try:
        spec = sources.SourceSpec("new-source", 3, "test-strategy", "https://new.test/feed")
        session = Session({spec.url: Response("ignored")})
        assert [a.title for a in sources.fetch(spec, session, limit=5)] == ["from registry"]
    finally:
        del sources._STRATEGIES["test-strategy"]


def test_fetch_rejects_unknown_strategy():
    spec = sources.SourceSpec("bad", 1, "no-such-strategy", "https://bad.test")
    with pytest.raises(ValueError):
        sources.fetch(spec, Session({spec.url: Response("ignored")}), limit=1)


def test_the_shipped_source_config_loads():
    """It is committed config; a broken one breaks every `run` for everybody."""
    specs = sources.load_specs()
    assert set(specs) == {"khabarfoori", "mehr", "shahrekhabar"}
    assert all(spec.strategy in sources._STRATEGIES for spec in specs.values())


# ------------------------------------------------------------------------ backfill


def test_backfill_khabarfoori_stops_once_an_article_predates_the_window():
    spec = sources.SourceSpec("khabarfoori", 2, "listing_detail", "https://site.test/list")
    session = Session({
        spec.url: Response("""<ul class="box container">
            <li><h2 class="title"><a href="/news/known">known</a></h2></li>
            <li><h2 class="title"><a href="/news/1">new</a></h2></li></ul>"""),
        f"{spec.url}/?page=2": Response("""<ul class="box container">
            <li><h2 class="title"><a href="/news/2">older</a></h2></li></ul>"""),
        "https://site.test/news/1": Response(khabarfoori_page(
            paragraphs=["enough content here for extraction."], published="2026-08-10T10:00:00+03:30")),
        "https://site.test/news/2": Response(khabarfoori_page(
            paragraphs=["enough content here for extraction."], published="2026-07-01T10:00:00+03:30")),
    })
    articles = list(sources.backfill_fetch(
        spec, session, since_date="2026-08-05", known_urls={"https://site.test/news/known"}))
    # Page 3 was never requested (it is absent from `responses` and would KeyError) -
    # since_date was crossed on page 2, so the loop stopped there.
    assert [a.url for a in articles] == ["https://site.test/news/1", "https://site.test/news/2"]


def test_backfill_stops_after_consecutive_pages_with_nothing_new():
    spec = sources.SourceSpec("khabarfoori", 2, "listing_detail", "https://site.test/list")
    known = """<ul class="box container">
        <li><h2 class="title"><a href="/news/known">known</a></h2></li></ul>"""
    session = Session({spec.url: Response(known), f"{spec.url}/?page=2": Response(known)})
    assert list(sources.backfill_fetch(
        spec, session, since_date="2020-01-01", known_urls={"https://site.test/news/known"})) == []


def test_backfill_mehr_walks_each_category_archive_endpoint():
    article = """
    <script type="application/ld+json">{"@type":"NewsArticle","headline":"t",
    "description":"d","datePublished":"2026-08-10T10:00:00+03:30"}</script>
    <article><p>enough content here for the extractor to accept as a real body.</p></article>
    """
    spec = sources.SourceSpec("mehr", 1, "rss", "https://www.mehrnews.com/rss")
    responses = {}
    for topic in sources._MEHR_ARCHIVE_CATEGORIES:
        base = sources._MEHR_ARCHIVE_URL
        responses[f"{base}?tp={topic}&pi=1"] = Response(
            f'<li class="news"><div class="desc"><h3><a href="/news/{topic}/x">t</a></h3></div></li>')
        responses[f"{base}?tp={topic}&pi=2"] = Response("<ul></ul>")
        responses[f"{base}?tp={topic}&pi=3"] = Response("<ul></ul>")
        responses[f"https://www.mehrnews.com/news/{topic}/x"] = Response(article)

    articles = sources.backfill_fetch(spec, Session(responses), since_date="2026-08-01", known_urls=set())
    assert {a.url for a in articles} == {
        f"https://www.mehrnews.com/news/{topic}/x" for topic in sources._MEHR_ARCHIVE_CATEGORIES
    }


def test_backfill_yields_nothing_for_a_source_without_a_history_mechanism():
    """shahrekhabar has no archive/date endpoint - an honest limitation, not a guess."""
    spec = sources.SourceSpec("shahrekhabar", 2, "listing_relay", "https://shahr.test/list")
    assert list(sources.backfill_fetch(spec, since_date="2020-01-01", known_urls=set())) == []


# -------------------------------------------------------------------- quality gate


def article(**overrides):
    base = dict(
        source="khabarfoori", url="https://example.test/1",
        title="حمله موشکی به تاسیسات نفتی کشور", lead="جزئیات بیشتر از این حادثه",
        content="متن کامل خبر با جزئیات فراوان", published_at="2026-08-16T10:00:00+03:30",
    )
    return sources.RawArticle(**{**base, **overrides})


class TestQualityGate:
    @pytest.mark.parametrize("overrides", [
        {},
        {"content": ""},          # photo posts have no body; title + lead is enough
        {"published_at": None},
        {"published_at": "پنجشنبه"},  # unparseable date must not crash
        {"published_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()},
    ])
    def test_accepted(self, overrides):
        assert pipeline.quality_reason(article(**overrides)) is None

    @pytest.mark.parametrize("overrides,reason", [
        ({"title": ""}, "missing_title"),
        ({"title": "خبر"}, "title_too_short"),
        ({"title": "خبر کوتاه ی", "lead": "", "content": ""}, "insufficient_text"),
        ({"url": ""}, "invalid_url"),
        ({"url": "not-a-url"}, "invalid_url"),
        ({"url": "ftp://x.test/a"}, "invalid_url"),
        ({"url": "javascript:alert(1)"}, "invalid_url"),
    ])
    def test_rejected(self, overrides, reason):
        assert pipeline.quality_reason(article(**overrides)) == reason

    def test_a_future_date_is_rejected(self):
        """A future timestamp is a misparsed date, and a wrong date silently breaks
        dedup's time window and the workbook's daily grouping."""
        ahead = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        assert pipeline.quality_reason(article(published_at=ahead)) == "published_in_future"


def test_backfill_dispatch_cannot_drift_from_the_supported_set():
    """A name in BACKFILLABLE with no handler used to fall through to Mehr's archive,
    silently paginating the wrong site. The set is now derived from the handler table."""
    assert sources.BACKFILLABLE == set(sources._BACKFILL)
    assert set(sources._BACKFILL) <= set(sources.load_specs()), \
        "every backfillable name must be a real configured source"
