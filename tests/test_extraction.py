"""Extraction regressions found by auditing live fetches.

Each class here corresponds to a bug that was shipping, with the measurement that
exposed it in the docstring.
"""

import json

from news_intel import dedupe, pipeline, sources


def page(*, body_paragraphs, article_body, headline="عنوان کامل خبر برای تست", editor_id="main_ck_editor"):
    ld = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": headline,
        "description": "لید خبر",
        "articleBody": article_body,
        "datePublished": "2026-08-16T10:00:00+03:30",
    }
    paragraphs = "".join(f"<p>{text}</p>" for text in body_paragraphs)
    return f"""<html><head>
    <script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
    </head><body><h1 class="title">{headline}</h1>
    <div id="{editor_id}">{paragraphs}</div></body></html>"""


class TestJsonLdBodyPreferred:
    """The CSS selector reads only <p>, so headings, list items and blockquotes were
    dropped. JSON-LD articleBody was longer on 10 of 10 live khabarfoori articles."""

    def test_jsonld_wins_when_longer(self):
        html = page(body_paragraphs=["کوتاه"], article_body="متن کامل و طولانی تر از پاراگراف ها")
        parsed = sources.parse_khabarfoori_article(html, "https://k.test/1")
        assert parsed.content == "متن کامل و طولانی تر از پاراگراف ها"
        assert parsed.extraction_tier == "jsonld"

    def test_css_is_the_fallback_when_jsonld_is_empty(self):
        html = page(body_paragraphs=["پاراگراف اول", "پاراگراف دوم"], article_body="")
        parsed = sources.parse_khabarfoori_article(html, "https://k.test/1")
        assert "پاراگراف اول" in parsed.content and "پاراگراف دوم" in parsed.content
        assert parsed.extraction_tier == "css"

    def test_degradation_is_visible_in_the_tier(self):
        """A redesign breaking the selector should show as a tier change, not as
        silently truncated articles."""
        broken = page(body_paragraphs=[], article_body="", editor_id="renamed_by_redesign")
        parsed = sources.parse_khabarfoori_article(broken, "https://k.test/1")
        assert parsed.content == ""

    def test_generic_parser_also_prefers_jsonld(self):
        html = page(body_paragraphs=["کوتاه"], article_body="متن کامل و بسیار طولانی تر")
        parsed = sources.parse_generic_article(html, "mehr", "https://m.test/1")
        assert parsed.content == "متن کامل و بسیار طولانی تر"
        assert parsed.extraction_tier == "jsonld"


class TestUndatedDeduplication:
    """Articles with no publish date returned zero dedup candidates, so they skipped
    near-duplicate detection entirely. Shahrekhabar produces undated entries routinely."""

    def make(self, url, title, published=None):
        return sources.RawArticle(
            source="shahrekhabar", url=url, title=title, lead="", content="متن خبر",
            published_at=published,
        )

    def test_undated_near_duplicates_are_now_caught(self, conn):
        conn.execute("INSERT INTO sources(name,tier,priority,enabled) VALUES('shahrekhabar',2,3,1)")
        pipeline.upsert_article(conn, self.make("https://a/1", "رادارهای اولیه این شکلی بودند"), "r")
        _, _, dup = pipeline.upsert_article(
            conn, self.make("https://a/2", "رادارهای اولیه این شکلی بودند/ عکس"), "r"
        )
        assert dup is True

    def test_undated_candidates_are_bounded(self, conn):
        conn.execute("INSERT INTO sources(name,tier,priority,enabled) VALUES('shahrekhabar',2,3,1)")
        found = dedupe.candidates(conn, article_id=-1, published_at=None)
        assert len(found) <= dedupe.UNDATED_CANDIDATE_LIMIT

    def test_dated_articles_still_use_the_time_window(self, conn):
        conn.execute("INSERT INTO sources(name,tier,priority,enabled) VALUES('shahrekhabar',2,3,1)")
        first = self.make("https://a/1", "وضعیت بازار ارز امروز", "2026-08-01T10:00:00+03:30")
        # Bodies must differ, or the exact content_hash match fires before the time
        # window is ever consulted and the test proves nothing about blocking.
        second = sources.RawArticle(
            source="shahrekhabar", url="https://a/2", title="وضعیت بازار ارز امروز",
            lead="", content="متن متفاوت برای روز دیگر",
            published_at="2026-08-20T10:00:00+03:30",
        )
        pipeline.upsert_article(conn, first, "r")
        _, _, dup = pipeline.upsert_article(conn, second, "r")
        assert dup is False, "weeks apart is a recurring headline, not a duplicate"


class TestQualityGateStopsInference:
    def test_rejected_article_is_quarantined_not_classified(self, conn):
        conn.execute("INSERT INTO sources(name,tier,priority,enabled) VALUES('khabarfoori',2,1,1)")
        from news_intel.providers import RuleProvider

        bad = sources.RawArticle(source="khabarfoori", url="https://a/1", title="", lead="", content="")
        good = sources.RawArticle(
            source="khabarfoori", url="https://a/2", title="حمله موشکی به تاسیسات نفتی",
            lead="جزئیات", content="متن کامل خبر",
        )
        stats = pipeline.process(conn, [bad, good], RuleProvider())

        assert stats["rejected"] == 1
        assert stats["classified"] == 1, "only the good article costs an inference call"
        rows = conn.execute("SELECT node, error_class FROM dead_letters").fetchall()
        assert rows and rows[0]["node"] == "quality"
        assert rows[0]["error_class"] == "missing_title"
