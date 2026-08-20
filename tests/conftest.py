import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news_intel import dag, db  # noqa: E402
from news_intel.sources import RawArticle  # noqa: E402

# A realistic headline: the quality gate rejects stubs like "خبر" before inference, which
# is the point of the gate but makes them useless as pipeline fixtures.
NEWS = RawArticle(
    source="khabarfoori",
    url="https://example.test/gold",
    title="حمله موشکی به تاسیسات و جهش قیمت طلا در بازار تهران",
    lead="گزارش خبرگزاری از واکنش بازار",
    content="متن کامل خبر درباره حمله و اثر آن بر قیمت طلا و دلار در بازار داخلی امروز.",
    original_outlet="ایسنا",
    published_at="2026-08-16T10:00:00+03:30",
)


@pytest.fixture
def conn(tmp_path):
    connection = db.init_db(tmp_path / "test.db")
    yield connection
    connection.close()


@pytest.fixture
def ctx(conn):
    context = dag.Ctx(conn=conn, run_id="test_run", costs=dag.CostMeter(budget_usd=1.0))
    dag.start_run(conn, "test_run", "test")
    return context


@pytest.fixture
def article_id(conn):
    """A real article row, so foreign keys on node_events/dead_letters resolve."""
    return db.insert(conn, "articles", {
        "url": "https://example.test/1", "identity_key": "id:1", "source": "test",
        "content_hash": "hash1", "fetched_at": "2026-01-01T00:00:00+03:30",
    })


def store_article(conn, url, **overrides):
    """Insert a bare article row directly, bypassing the pipeline."""
    row = {
        "url": url, "identity_key": f"id:{url}", "source": "test", "original_title": "t",
        "lead": "l", "content": "c", "content_hash": url,
        "fetched_at": "2026-01-01T00:00:00+03:30",
    }
    row.update(overrides)
    return db.insert(conn, "articles", row)
