import json

import pytest

from news_intel.core import db
from news_intel.evals import EvaluationCase, Variant, build_golden, compare, evaluate, load_cases, weighted_kappa
from news_intel.providers import RuleProvider
from news_intel.sources import RawArticle


def review_case(conn, *, url, status, category=None, scores=None, title="خبر آزمایشی درباره طلا"):
    article_id = db.insert(conn, "articles", {
        "url": url, "identity_key": f"id:{url}", "source": "test",
        "original_title": title, "lead": "لید", "content": "متن",
        "content_hash": url, "fetched_at": "2026-01-01T00:00:00+03:30",
    })
    db.insert(conn, "review_cases", {
        "article_id": article_id, "stratum": "test", "status": status,
        "reviewed_category": category, "created_at": "2026-01-01T00:00:00+03:30",
        **(scores or {}),
    })
    return article_id


def test_weighted_kappa_is_perfect_for_matching_ordinal_scores():
    assert weighted_kappa([1, 3, 5], [1, 3, 5]) == 1.0


def test_evaluation_report_uses_category_and_ordinal_metrics():
    case = EvaluationCase(
        article=RawArticle(source="test", url="https://test/1", title="حمله و طلا"),
        category="security/economics",
        scores={"confidence_occurrence": "زیاد", "gold_price_impact": "زیاد", "security_relevance": "زیاد"},
    )
    report = evaluate([case], RuleProvider())
    assert report["category_accuracy"] == 1.0
    assert report["kappa"]["gold_price_impact"] is None


def test_golden_set_is_built_only_from_approved_reviews(conn, tmp_path):
    """Pending and skipped rows carry no human judgement and must not become truth."""
    review_case(conn, url="https://test/approved", status="approved", category="economics")
    review_case(conn, url="https://test/pending", status="pending")
    review_case(conn, url="https://test/skipped", status="skipped")

    path = tmp_path / "golden.json"
    assert build_golden(conn, path) == 1
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert [case["article"]["url"] for case in cases] == ["https://test/approved"]


def test_an_axis_the_reviewer_left_unassessed_is_absent_not_defaulted(conn, tmp_path):
    """The legacy bug in miniature: an unjudged axis must contribute nothing at all."""
    review_case(
        conn, url="https://test/partial", status="approved", category="security",
        scores={"confidence_occurrence": "زیاد", "security_relevance": "خیلی زیاد"},
    )
    path = tmp_path / "golden.json"
    build_golden(conn, path)
    scores = json.loads(path.read_text(encoding="utf-8"))[0]["scores"]
    assert scores == {"confidence_occurrence": "زیاد", "security_relevance": "خیلی زیاد"}
    assert "gold_price_impact" not in scores


def test_the_built_golden_set_loads_back_as_evaluation_cases(conn, tmp_path):
    """Round trip: build_golden writes exactly what load_cases and `evaluate` consume."""
    review_case(
        conn, url="https://test/roundtrip", status="approved", category="security/economics",
        scores={"confidence_occurrence": "زیاد", "gold_price_impact": "زیاد",
                "security_relevance": "زیاد"},
        title="حمله موشکی و اثر آن بر قیمت طلا",
    )
    path = tmp_path / "golden.json"
    build_golden(conn, path)
    cases = load_cases(path)
    assert len(cases) == 1
    assert cases[0].category == "security/economics"
    assert evaluate(cases, RuleProvider())["category_accuracy"] == 1.0


def test_an_empty_review_queue_produces_an_empty_set_rather_than_failing(conn, tmp_path):
    path = tmp_path / "golden.json"
    assert build_golden(conn, path) == 0
    assert json.loads(path.read_text(encoding="utf-8")) == []


def _article(conn, url):
    return db.insert(conn, "articles", {
        "url": url, "identity_key": f"id:{url}", "source": "test",
        "original_title": f"عنوان {url}", "lead": "لید", "content": "متن",
        "content_hash": url, "fetched_at": "2026-01-01T00:00:00+03:30",
    })


def _inference(conn, article_id, *, provider, version, category, occurrence, gold, security):
    db.insert(conn, "classifications", {
        "article_id": article_id, "category": category, "confidence": "زیاد",
        "rationale": "r", "method": "llm", "prompt_version": version,
        "provider": provider, "model": "m1", "run_id": "r1", "created_at": "2026-01-01T00:00:00",
    })
    db.insert(conn, "evaluations", {
        "article_id": article_id, "confidence_occurrence": occurrence,
        "gold_price_impact": gold, "security_relevance": security, "gold_trend": "↑",
        "rationale": "r", "prompt_version": version, "provider": provider,
        "model": "m1", "run_id": "r1", "created_at": "2026-01-01T00:00:00",
    })


def test_compare_splits_agreeing_and_diverging_articles_into_separate_files(conn, tmp_path):
    same_id, diff_id = _article(conn, "https://test/same"), _article(conn, "https://test/diff")
    a, b = Variant("gapgpt", "m1", "va"), Variant("gapgpt", "m1", "vb")
    for article_id in (same_id, diff_id):
        _inference(conn, article_id, provider="gapgpt", version="va", category="security",
                   occurrence="زیاد", gold="زیاد", security="زیاد")
    # Variant B agrees on `same_id`, diverges on `diff_id` (different category).
    _inference(conn, same_id, provider="gapgpt", version="vb", category="security",
               occurrence="زیاد", gold="زیاد", security="زیاد")
    _inference(conn, diff_id, provider="gapgpt", version="vb", category="economics",
               occurrence="زیاد", gold="زیاد", security="زیاد")

    out_dir = tmp_path / "compare"
    summary = compare(conn, a=a, b=b, out_dir=out_dir)

    assert summary == {"shared_articles": 2, "same": 1, "different": 1, "out_dir": str(out_dir)}
    assert "same" in (out_dir / "comparison_same.txt").read_text(encoding="utf-8")
    diff_text = (out_dir / "comparison_different.txt").read_text(encoding="utf-8")
    assert "category=security" in diff_text and "category=economics" in diff_text
    all_text = (out_dir / "comparison_all.txt").read_text(encoding="utf-8")
    assert all_text.count("same | ") == 1 and all_text.count("different | ") == 1


def test_compare_fails_loudly_when_a_variant_was_never_run(conn, tmp_path):
    with pytest.raises(ValueError):
        compare(conn, a=Variant("gapgpt", None, "va"), b=Variant("gapgpt", None, "vb"), out_dir=tmp_path)
