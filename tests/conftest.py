import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news_intel.core import dag, db  # noqa: E402


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
    return db.insert(
        conn,
        "articles",
        {
            "url": "https://example.test/1",
            "identity_key": "id:1",
            "source": "test",
            "content_hash": "hash1",
            "fetched_at": "2026-01-01T00:00:00+03:30",
        },
    )
