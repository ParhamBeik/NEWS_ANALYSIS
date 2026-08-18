from news_intel import reviews
from news_intel.core import db


def test_review_queue_exports_requested_cases(conn, article_id, tmp_path):
    db.insert(conn, "classifications", {
        "article_id": article_id, "category": "security", "confidence": "زیاد",
        "method": "legacy", "run_id": "legacy", "created_at": "2026-01-01T00:00:00+03:30",
    })
    assert reviews.create_queue(conn, size=1) == 1
    output = reviews.export_queue(conn, tmp_path / "review.xlsx")
    assert output.exists()
