"""Cross-source deduplication.

Threshold constants here are the ones measured against the production corpus; the
false-positive cases below are real title pairs taken from it, not invented.
"""

import pytest

from news_intel import dedupe, pipeline, sources
from news_intel.core import db


def article(url, title, *, source="khabarfoori", content="جزئیات خبر", published="2026-08-16T10:00:00+03:30"):
    return sources.RawArticle(
        source=source, url=url, title=title, lead="", content=content,
        published_at=published,
    )


def register_sources(conn):
    conn.execute("INSERT OR REPLACE INTO sources(name,tier,priority,enabled) VALUES('khabarfoori',2,1,1)")
    conn.execute("INSERT OR REPLACE INTO sources(name,tier,priority,enabled) VALUES('mehr',1,2,1)")
    conn.execute("INSERT OR REPLACE INTO sources(name,tier,priority,enabled) VALUES('shahrekhabar',2,3,1)")


def add(conn, art, run_id="r1"):
    return pipeline.upsert_article(conn, art, run_id)


def canonical_count(conn):
    return conn.execute("SELECT COUNT(*) c FROM articles WHERE duplicate_of IS NULL").fetchone()["c"]


class TestExactDuplicates:
    def test_identical_content_is_deduplicated(self, conn):
        register_sources(conn)
        add(conn, article("https://a.test/1", "حمله موشکی به تاسیسات"))
        _, _, dup = add(conn, article("https://b.test/2", "حمله موشکی به تاسیسات"))
        assert dup is True
        assert canonical_count(conn) == 1

    def test_encoding_variants_collide(self, conn):
        """Arabic KAF vs Persian KEHEH is the same story, not two."""
        register_sources(conn)
        add(conn, article("https://a.test/1", "حمله موشكی به تاسیسات"))  # Arabic KAF
        _, _, dup = add(conn, article("https://b.test/2", "حمله موشکی به تاسیسات"))
        assert dup is True


class TestNearDuplicates:
    @pytest.mark.parametrize(
        "left,right",
        [
            # Real pairs from the production corpus, all scoring >= 0.70.
            ("گسترده ترین حمله موشکی ایران در هفته های اخیر | انفجار در شهرک",
             "گسترده ترین حمله موشکی ایران در هفته های اخیر؛ انفجار در شهرک"),
            ("رادارهای اولیه این شکلی بودند", "رادارهای اولیه این شکلی بودند/ عکس"),
            ("چگونه در بحران، آرامش خود را حفظ کنیم؟", "چگونه در بحران آرامش خود را حفظ کنیم؟"),
            ("نفتکش حامل نفت خام ایران از تنگه هرمز عبور کرد/ عکس",
             "نفتکش حامل نفت خام ایران از تنگه هرمز عبور کرد"),
        ],
    )
    def test_reworded_titles_are_merged(self, conn, left, right):
        register_sources(conn)
        add(conn, article("https://a.test/1", left, content="متن یک"))
        _, _, dup = add(conn, article("https://b.test/2", right, content="متن دو"))
        assert dup is True
        assert canonical_count(conn) == 1

    @pytest.mark.parametrize(
        "left,right",
        [
            # Also real pairs, scoring 0.5-0.62. Different articles sharing a date template.
            ("فال قهوه سه شنبه یک اردیبهشت ۱۴۰۵", "فال روزانه سه شنبه یک اردیبهشت 1405"),
            ("فال انبیا چهارشنبه ۲ اردیبهشت ۱۴۰۵", "فال روزانه چهارشنبه 2 اردیبهشت ۱۴۰۵"),
            ("صفحه نخست روزنامه ها چهارشنبه ۲ اردیبهشت ۱۴۰۵",
             "فال انبیا چهارشنبه ۲ اردیبهشت ۱۴۰۵"),
            # The one false positive at 0.704: two different cities sharing the بندر stem.
            # This pair is why the threshold sits at 0.75 rather than 0.70.
            ("احتمال شنیده شدن صدای انفجارهای کنترل شده در شرق شهر بندرعباس",
             "احتمال شنیده شدن صدای انفجارهای کنترل شده در بندرلنگه"),
        ],
    )
    def test_date_templated_titles_are_not_merged(self, conn, left, right):
        """Why the threshold is 0.75 and not lower."""
        register_sources(conn)
        add(conn, article("https://a.test/1", left, content="متن یک"))
        _, _, dup = add(conn, article("https://b.test/2", right, content="متن دو"))
        assert dup is False
        assert canonical_count(conn) == 2

    def test_unrelated_stories_stay_separate(self, conn):
        register_sources(conn)
        add(conn, article("https://a.test/1", "افزایش قیمت طلا در بازار تهران"))
        _, _, dup = add(conn, article("https://b.test/2", "برگزاری مسابقات فوتبال جوانان"))
        assert dup is False
        assert canonical_count(conn) == 2


class TestTimeWindowBlocking:
    def test_same_title_outside_the_window_is_not_merged(self, conn):
        """A recurring headline weeks apart is a new story, not a duplicate."""
        register_sources(conn)
        add(conn, article("https://a.test/1", "وضعیت بازار ارز امروز",
                          content="a", published="2026-08-01T10:00:00+03:30"))
        _, _, dup = add(conn, article("https://b.test/2", "وضعیت بازار ارز امروز",
                                      content="b", published="2026-08-20T10:00:00+03:30"))
        assert dup is False

    def test_missing_timestamp_skips_near_matching(self, conn):
        register_sources(conn)
        add(conn, article("https://a.test/1", "خبر بدون تاریخ", content="a"))
        _, _, dup = add(conn, article("https://b.test/2", "خبر بدون تاریخ نیست",
                                      content="b", published=None))
        assert dup is False


class TestCanonicalSelection:
    def test_higher_priority_source_becomes_canonical(self, conn):
        """Mehr arrives first, Khabarfoori second with a fuller body: Khabarfoori wins."""
        register_sources(conn)
        first, _, _ = add(conn, article("https://mehr.test/1", "حمله موشکی به تاسیسات نفتی",
                                        source="mehr", content="خلاصه کوتاه"))
        second, _, _ = add(conn, article("https://kf.test/2", "حمله موشکی به تاسیسات نفتی",
                                         source="khabarfoori", content="متن کامل خبر"))
        rows = {r["id"]: r["duplicate_of"] for r in conn.execute("SELECT id, duplicate_of FROM articles")}
        assert rows[second] is None, "khabarfoori (priority 1) must be canonical"
        assert rows[first] == second

    def test_lower_priority_arrival_does_not_displace(self, conn):
        register_sources(conn)
        first, _, _ = add(conn, article("https://kf.test/1", "حمله موشکی به تاسیسات نفتی",
                                        source="khabarfoori", content="متن کامل"))
        second, _, _ = add(conn, article("https://sk.test/2", "حمله موشکی به تاسیسات نفتی",
                                         source="shahrekhabar", content=""))
        rows = {r["id"]: r["duplicate_of"] for r in conn.execute("SELECT id, duplicate_of FROM articles")}
        assert rows[first] is None
        assert rows[second] == first

    def test_longer_content_wins_within_the_same_source(self, conn):
        register_sources(conn)
        first, _, _ = add(conn, article("https://a.test/1", "خبر مهم امنیتی", content="کوتاه"))
        second, _, _ = add(conn, article("https://a.test/2", "خبر مهم امنیتی",
                                         content="متن بسیار طولانی تر از نسخه اول"))
        rows = {r["id"]: r["duplicate_of"] for r in conn.execute("SELECT id, duplicate_of FROM articles")}
        assert rows[second] is None
        assert rows[first] == second

    def test_duplicate_chain_never_exceeds_one_level(self, conn):
        """Demoting a canonical must repoint its followers, or `duplicate_of IS NULL`
        stops being a reliable "this is the story" filter."""
        register_sources(conn)
        a, _, _ = add(conn, article("https://sk.test/1", "حمله موشکی به تاسیسات نفتی",
                                    source="shahrekhabar", content=""))
        b, _, _ = add(conn, article("https://mehr.test/2", "حمله موشکی به تاسیسات نفتی",
                                    source="mehr", content="خلاصه"))
        c, _, _ = add(conn, article("https://kf.test/3", "حمله موشکی به تاسیسات نفتی",
                                    source="khabarfoori", content="متن کامل خبر"))
        rows = {r["id"]: r["duplicate_of"] for r in conn.execute("SELECT id, duplicate_of FROM articles")}
        assert rows[c] is None
        assert rows[a] == c and rows[b] == c, "no duplicate may point at another duplicate"
        assert canonical_count(conn) == 1


class TestBlockingIsBounded:
    def test_candidates_are_limited_to_the_window(self, conn):
        register_sources(conn)
        # Titles must be genuinely unrelated, or they dedupe into each other and the
        # candidate pool is 1. Numbered variants of one sentence are near-identical.
        topics = ["طلا", "نفت", "گندم", "مسکن", "خودرو", "بورس", "ارز", "بیمه", "مالیات", "بودجه"]
        for i, topic in enumerate(topics):
            add(conn, article(f"https://a.test/{i}", f"گزارش کامل درباره وضعیت {topic} در کشور",
                              content=f"متن {i}", published="2026-08-16T10:00:00+03:30"))
        for i, topic in enumerate(topics, start=100):
            add(conn, article(f"https://a.test/{i}", f"گزارش کامل درباره وضعیت {topic} در کشور",
                              content=f"متن {i}", published="2026-01-01T10:00:00+03:30"))
        near = dedupe.candidates(conn, article_id=-1, published_at="2026-08-16T10:00:00+03:30")
        assert len(near) == len(topics), "articles months away must not be compared"


class TestBackfill:
    def test_dry_run_reports_each_pair_once(self, conn):
        """Without linking there is nothing to suppress the reverse match, so the naive
        version reports A->B and B->A and doubles the count."""
        register_sources(conn)
        add(conn, article("https://a.test/1", "رادارهای اولیه این شکلی بودند", content="a"))
        add(conn, article("https://b.test/2", "رادارهای اولیه این شکلی بودند/ عکس", content="b"))
        conn.execute("UPDATE articles SET duplicate_of = NULL")  # undo ingest-time linking

        merged = dedupe.backfill(conn, dry_run=True)
        assert len(merged) == 1

    def test_dry_run_changes_nothing(self, conn):
        register_sources(conn)
        add(conn, article("https://a.test/1", "رادارهای اولیه این شکلی بودند", content="a"))
        add(conn, article("https://b.test/2", "رادارهای اولیه این شکلی بودند/ عکس", content="b"))
        conn.execute("UPDATE articles SET duplicate_of = NULL")

        dedupe.backfill(conn, dry_run=True)
        assert canonical_count(conn) == 2

    def test_apply_links_the_matches(self, conn):
        register_sources(conn)
        add(conn, article("https://a.test/1", "رادارهای اولیه این شکلی بودند", content="a"))
        add(conn, article("https://b.test/2", "رادارهای اولیه این شکلی بودند/ عکس", content="b"))
        conn.execute("UPDATE articles SET duplicate_of = NULL")

        assert len(dedupe.backfill(conn)) == 1
        assert canonical_count(conn) == 1

    def test_is_idempotent(self, conn):
        register_sources(conn)
        add(conn, article("https://a.test/1", "رادارهای اولیه این شکلی بودند", content="a"))
        add(conn, article("https://b.test/2", "رادارهای اولیه این شکلی بودند/ عکس", content="b"))
        dedupe.backfill(conn)
        assert dedupe.backfill(conn) == [], "a second pass must find nothing"


class TestResolveContract:
    def test_returns_none_when_unique(self, conn):
        register_sources(conn)
        article_id, _, _ = add(conn, article("https://a.test/1", "یک خبر کاملا منحصر به فرد"))
        match = dedupe.find_duplicate(
            conn, article_id=article_id, title="عنوان بی ربط دیگر",
            content_hash="nothing", published_at="2026-08-16T10:00:00+03:30",
        )
        assert match is None

    def test_reports_reason_and_score(self, conn):
        register_sources(conn)
        add(conn, article("https://a.test/1", "رادارهای اولیه این شکلی بودند"))
        article_id, _, _ = add(conn, article("https://b.test/2", "رادارهای اولیه این شکلی بودند/ عکس",
                                             content="دیگر"))
        row = conn.execute("SELECT duplicate_of FROM articles WHERE id=?", (article_id,)).fetchone()
        assert row["duplicate_of"] is not None

    def test_empty_title_is_not_matched(self, conn):
        register_sources(conn)
        assert dedupe.find_duplicate(
            conn, article_id=1, title="", content_hash="x",
            published_at="2026-08-16T10:00:00+03:30",
        ) is None
