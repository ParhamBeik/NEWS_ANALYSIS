from news_intel import sources


class Response:
    def __init__(self, text, status=200):
        self.text, self.status = text, status

    def raise_for_status(self):
        if self.status >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status}")


class Session:
    def __init__(self, responses):
        self.responses = responses

    def get(self, url, **_):
        return self.responses[url]


KHABARFOORI_LISTING = """
<ul class="box container"><li><div class="detail"><h2 class="title">
<a href="/news/1">خبر نمونه</a></h2></div></li></ul>
"""
KHABARFOORI_ARTICLE = """
<script type="application/ld+json">{"@type":"NewsArticle","headline":"عنوان ساختاریافته",
"description":"لید ساختاریافته","datePublished":"2026-08-16T10:00:00+03:30"}</script>
<div id="main_ck_editor"><p>بند اول خبر با متن کافی.</p><p>بند دوم خبر.</p></div>
<div class="source_news"><span class="source_title">منبع:</span><span>ایسنا</span></div>
"""
MEHR_FEED = """<rss><channel><item><title>خبر مهر</title><link>https://mehr.test/1</link>
<description>خلاصه</description><pubDate>Sun, 16 Aug 2026 10:00:00 +0330</pubDate></item></channel></rss>"""
SHAHR_LISTING = """<ul class="news-list-items"><li><a href="/a">خبر شهر</a>
<span class="refrence minw88">مهر</span></li></ul>"""


def test_khabarfoori_listing_and_article_are_structured_first():
    assert sources.parse_khabarfoori_listing(KHABARFOORI_LISTING, "https://site.test") == ["https://site.test/news/1"]
    article = sources.parse_khabarfoori_article(KHABARFOORI_ARTICLE, "https://site.test/news/1")
    assert article.title == "عنوان ساختاریافته"
    assert article.original_outlet == "ایسنا"
    assert article.content == "بند اول خبر با متن کافی.\nبند دوم خبر."
    assert article.date_uncertain is False


def test_mehr_rss_and_shahrekhabar_listing_normalize_to_raw_articles():
    mehr = sources.parse_mehr_feed(MEHR_FEED)
    shahr = sources.parse_shahrekhabar_listing(SHAHR_LISTING, "https://shahr.test")
    assert mehr[0].source == "mehr" and mehr[0].published_at
    assert shahr[0].source == "shahrekhabar"
    assert shahr[0].original_outlet == "مهر"


def test_shahrekhabar_relay_target_prefers_iframe():
    assert sources.shahrekhabar_target('<iframe src="https://origin.test/a"></iframe>', "https://relay.test/a") == "https://origin.test/a"


def test_shahrekhabar_skips_stale_relays_until_the_limit():
    listing = """<ul class="news-list-items">
    <li><a href="/stale">stale</a></li><li><a href="/live">live</a></li></ul>"""
    live = '<h1>live title</h1><p>This is enough article content for extraction.</p>'
    spec = sources.SourceSpec("shahrekhabar", 2, "listing_relay", "https://shahr.test/list")
    session = Session({
        spec.url: Response(listing),
        "https://shahr.test/stale": Response("", 404),
        "https://shahr.test/live": Response(live),
    })
    assert [article.title for article in sources.fetch(spec, session, limit=1)] == ["live title"]


def test_fetch_dispatches_by_strategy_not_by_source_name():
    """A 4th source reusing an existing strategy needs no change to fetch() itself."""

    @sources.strategy("test-strategy")
    def _handler(spec, session, response, limit):
        return [sources.RawArticle(source=spec.name, url=spec.url, title="from registry")]

    try:
        spec = sources.SourceSpec("new-source", 3, "test-strategy", "https://new.test/feed")
        session = Session({spec.url: Response("ignored")})
        assert [a.title for a in sources.fetch(spec, session, limit=5)] == ["from registry"]
    finally:
        del sources._STRATEGIES["test-strategy"]


def test_fetch_rejects_unknown_strategy():
    import pytest
    import requests

    spec = sources.SourceSpec("bad", 1, "no-such-strategy", "https://bad.test")
    session = Session({spec.url: Response("ignored")})
    with pytest.raises(ValueError):
        sources.fetch(spec, session, limit=1)
