"""The dashboard, its metrics, and everything downstream of a human label.

Exercised through real HTTP requests, because these cover the workflow a screenshot cannot
assert: that the model's answer is pre-selected, that "not assessed" round-trips to NULL
rather than a level, and that one submitted label reaches every consumer of review data.
"""

import json

import pytest

from news_intel import db, metrics, pipeline, providers, reviews
from news_intel.reviews import Variant
from news_intel.scoring import level_score
from news_intel.sources import RawArticle

from conftest import NEWS, store_article  # noqa: E402 - shared fixtures

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from news_intel import dashboard  # noqa: E402


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "news.db"
    with db.init_db(path) as conn:
        pipeline.process(conn, [NEWS], providers.RuleProvider(), run_id="run1")
        db.insert(conn, "review_cases", {
            "article_id": conn.execute("SELECT id FROM articles").fetchone()["id"],
            "stratum": "security/economics", "created_at": "2026-08-16T10:00:00+03:30",
        })
    with TestClient(dashboard.create_app(path)) as test_client:
        test_client.db_path = path
        yield test_client


def review_row(client):
    with db.connect(client.db_path, readonly=True) as conn:
        return conn.execute("SELECT * FROM review_cases").fetchone()


def approve(client, **fields):
    return client.post(f"/review/{review_row(client)['id']}",
                       data={"action": "approve", **fields})


# ------------------------------------------------------------------------------ pages


@pytest.mark.parametrize("route", ["/", "/review", "/kpi", "/ops", "/compare"])
def test_every_page_renders(client, route):
    response = client.get(route)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_the_review_page_shows_the_article_and_pre_selects_the_models_answer(client):
    """A reviewer corrects rather than fills; that is what makes the queue finishable."""
    body = client.get("/review").text
    assert NEWS.title in body and NEWS.content in body
    # RuleProvider classifies this article as security/economics.
    assert 'value="security/economics" checked' in body.replace(" >", ">")


def test_kpi_shows_an_empty_state_rather_than_fabricated_numbers(client):
    assert "No approved labels recorded yet." in client.get("/kpi").text


def test_home_lists_notify_worthy_news_in_english_chrome_with_persian_content(client):
    """RuleProvider gives this article three high axes - a real notify case."""
    body = client.get("/").text
    assert NEWS.title in body                 # article content itself stays Persian
    assert "Rolling window" in body           # surrounding chrome is English
    assert '<html lang="en">' in body


def test_a_long_persian_url_is_shortened_in_the_link_text_but_not_in_the_href(tmp_path):
    """Percent-encoded Persian slugs run past 200 characters; left alone they wrap over
    five lines and visually outweigh the article the reviewer is supposed to read. The
    href has to stay intact - only the label is cut."""
    url = "https://www.khabarfoori.com/" + "%D8%A7%D9%82%D8%AA%D8%B5%D8%A7%D8%AF" * 8
    assert len(url) > 200

    path = tmp_path / "news.db"
    with db.init_db(path) as conn:
        pipeline.process(conn, [RawArticle(
            source="khabarfoori", url=url, title=NEWS.title, lead=NEWS.lead, content=NEWS.content,
        )], providers.RuleProvider(), run_id="r")
        db.insert(conn, "review_cases", {
            "article_id": conn.execute("SELECT id FROM articles").fetchone()["id"],
            "stratum": "economics", "created_at": "2026-08-16T10:00:00+03:30",
        })
    with TestClient(dashboard.create_app(path)) as test_client:
        body = test_client.get("/review").text

    assert f'href="{url}"' in body, "the link must still go to the real article"
    label = body.split('rel="noopener">')[1].split("</a>")[0]
    assert "%D8" not in label, "the label must be decoded, not percent-encoded"
    assert label.endswith("…") and len(label) <= 72


def test_short_url_leaves_an_already_short_link_alone():
    assert dashboard._short_url("https://example.test/a") == "https://example.test/a"


# ----------------------------------------------------------------------------- submit


def test_submitting_a_label_stores_it_and_advances_the_queue(client):
    response = approve(client, reviewed_category="security", confidence_occurrence="خیلی زیاد",
                       gold_price_impact="کم", security_relevance="خیلی زیاد", gold_trend="↑",
                       one_line="خلاصه بازبین", reviewer_notes="یادداشت")
    assert response.status_code == 200  # followed the 303 back to /review

    row = review_row(client)
    assert row["status"] == "approved"
    assert row["reviewed_category"] == "security"
    assert row["confidence_occurrence"] == "خیلی زیاد"
    assert row["one_line"] == "خلاصه بازبین" and row["reviewed_at"] is not None
    assert "Every case in the review queue has been reviewed." in client.get("/review").text


def test_an_unassessed_axis_is_stored_as_null_not_as_a_level(client):
    """The legacy suppression bug, at the point where a human could re-introduce it. The
    form posts an empty string for "not assessed"; written as a level, or defaulted to the
    middle value, the notify floor would be computed from a judgement nobody made."""
    approve(client, reviewed_category="security", confidence_occurrence="زیاد",
            gold_price_impact="", security_relevance="زیاد", gold_trend="")
    row = review_row(client)
    assert row["gold_price_impact"] is None and row["gold_trend"] is None
    assert level_score(row["gold_price_impact"]) is None


def test_approving_without_a_category_is_refused(client):
    assert approve(client).status_code == 400
    assert review_row(client)["status"] == "pending"


def test_skipping_records_no_label(client):
    client.post(f"/review/{review_row(client)['id']}", data={"action": "skip"})
    row = review_row(client)
    assert row["status"] == "skipped" and row["reviewed_category"] is None


def test_reviewing_a_nonexistent_case_id_returns_404_not_a_silent_noop(client):
    """The `UPDATE ... WHERE id=?` used to match zero rows and still redirect as if the
    review had been recorded - a stale or hand-typed review_id was accepted silently."""
    assert client.post("/review/999999", data={"action": "skip"}).status_code == 404


def test_an_approved_label_reaches_the_kpi_page_and_the_next_run(client):
    """One submission has to move every downstream consumer, not just the stored row."""
    approve(client, reviewed_category="security",       # the model said security/economics
            confidence_occurrence="زیاد", gold_price_impact="", security_relevance="زیاد")

    with db.connect(client.db_path, readonly=True) as conn:
        report = metrics.compute(conn)
        examples = reviews.reviewed_examples(conn, NEWS, task="classify")

    assert (report.labelled, report.pending) == (1, 0)
    assert report.category_accuracy == 0.0, "the human disagreed with the model"
    assert report.confusion["security"]["security/economics"] == 1
    gold = next(a for a in report.axes if a.axis == "gold_price_impact")
    assert gold.disagreed_on_presence == 1, "human left it unassessed, model did not"
    assert [example.category for example in examples] == ["security"], \
        "the next classification must see what the human decided"

    page = client.get("/kpi").text
    assert "No approved labels recorded yet." not in page
    assert "Category confusion matrix" in page


def test_the_dashboard_cannot_lock_the_database_it_monitors(client):
    """Monitoring reads through a read-only connection; a writer stays unblocked."""
    with db.connect(client.db_path) as writer:
        client.get("/kpi")
        writer.execute("INSERT INTO sources(name,tier) VALUES('probe',1)")
        writer.commit()
    assert "probe" in client.get("/ops").text


# -------------------------------------------------------------------- home settings


def test_saving_the_window_setting_persists_and_redirects_home(client):
    response = client.post("/settings/window", data={"days": "30"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"
    with db.connect(client.db_path, readonly=True) as conn:
        assert db.get_setting(conn, "rolling_window_days", "14") == "30"


def test_saving_a_non_positive_window_clamps_to_one_day(client):
    client.post("/settings/window", data={"days": "-5"}, follow_redirects=False)
    with db.connect(client.db_path, readonly=True) as conn:
        assert db.get_setting(conn, "rolling_window_days", "14") == "1"


def test_saving_a_non_integer_window_is_rejected(client):
    assert client.post("/settings/window", data={"days": "abc"},
                       follow_redirects=False).status_code == 422


@pytest.mark.parametrize("page", [0, -1, 999])
def test_home_page_pagination_clamps_out_of_range_pages(client, page):
    assert client.get("/", params={"page": page}).status_code == 200


# -------------------------------------------------------------------------------- ops


def test_ops_page_shows_the_funnel_and_source_health(client):
    with db.connect(client.db_path) as conn:
        conn.execute("INSERT INTO sources(name,tier,config_path,priority,enabled,health_status)"
                     " VALUES('khabarfoori',2,'x',1,1,'healthy')")
        conn.commit()
    body = client.get("/ops").text
    assert "Pipeline Ops" in body and "khabarfoori" in body


def test_a_run_status_containing_markup_is_escaped_not_rendered(client):
    """The runs table used to be hand-built with partial `html.escape()` coverage and
    injected via `| safe`. Rendered as a real template, autoescaping covers every column by
    construction - pinned here with a value that would show as a live tag if it regressed."""
    with db.connect(client.db_path) as conn:
        conn.execute("INSERT INTO runs(run_id, mode, status, started_at) VALUES (?,?,?,?)",
                     ("probe-run", "live", "<script>alert(1)</script>", "2026-08-16T10:00:00+03:30"))
        conn.commit()
    body = client.get("/ops").text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


def test_api_telemetry_returns_the_four_aggregations(client):
    payload = client.get("/api/telemetry?days=7").json()
    assert set(payload) == {"token_cost_by_day", "node_status_counts",
                            "provider_breakdown", "fetch_volume_by_source"}
    assert payload["fetch_volume_by_source"][0]["source"] == "khabarfoori"


# --------------------------------------------------------------------- telemetry SQL


def event(conn, *, node, status, provider="gapgpt", model="m1", tokens_in=10, tokens_out=5, cost=0.01):
    from news_intel import dag
    db.insert(conn, "node_events", {
        "run_id": "r1", "node": node, "node_version": "v1", "cache_key": "k", "status": status,
        "attempt": 1, "tokens_in": tokens_in, "tokens_out": tokens_out, "cost_usd": cost,
        "provider": provider, "model": model, "created_at": dag.utc_now(),
    })


def recent_article(conn, *, source, url, duplicate_of=None):
    # `days=1` windows filter on date('now', ...), so fixtures must use the real clock -
    # a fixed literal passes today and silently starts failing tomorrow.
    from news_intel import dag
    return store_article(conn, url, source=source, fetched_at=dag.utc_now(), duplicate_of=duplicate_of)


def test_token_cost_and_node_status_aggregate_across_events(conn):
    event(conn, node="classify", status="success")
    event(conn, node="classify", status="exhausted")
    event(conn, node="evaluate", status="success", tokens_in=20, tokens_out=8, cost=0.02)

    rows = metrics.token_cost_by_day(conn, days=1)
    assert len(rows) == 1 and rows[0]["tokens_in"] == 40 and rows[0]["tokens_out"] == 18

    counts = {(r["node"], r["status"]): r["n"] for r in metrics.node_status_counts(conn, days=1)}
    assert counts[("classify", "success")] == 1 and counts[("classify", "exhausted")] == 1


def test_provider_breakdown_groups_by_provider_and_model(conn):
    event(conn, node="classify", status="success", provider="gapgpt", model="a")
    event(conn, node="classify", status="success", provider="ollama", model="b")
    rows = {(r["provider"], r["model"]): r["calls"] for r in metrics.provider_breakdown(conn, days=1)}
    assert rows[("gapgpt", "a")] == 1 and rows[("ollama", "b")] == 1


def test_funnel_excludes_duplicates_and_counts_inference_stages(conn):
    canonical = recent_article(conn, source="khabarfoori", url="https://t/1")
    recent_article(conn, source="khabarfoori", url="https://t/2", duplicate_of=canonical)
    db.insert(conn, "classifications", {
        "article_id": canonical, "category": "economics", "confidence": "زیاد", "method": "llm",
        "prompt_version": "v1", "provider": "gapgpt", "model": "m1", "run_id": "r1",
        "created_at": "2026-01-01T00:00:00",
    })
    funnel = metrics.funnel(conn, days=1)
    assert funnel == {"fetched": 2, "unique": 1, "classified": 1, "evaluated": 0}

    volume = {r["source"]: r["n"] for r in metrics.fetch_volume_by_source(conn, days=1)}
    assert volume["khabarfoori"] == 2


def test_source_coverage_flags_which_sources_can_backfill(conn):
    conn.execute("INSERT INTO sources(name, tier, config_path, priority, enabled)"
                 " VALUES('khabarfoori', 2, 'x', 1, 1), ('shahrekhabar', 2, 'x', 3, 1)")
    rows = {r["source"]: r for r in metrics.source_coverage(conn, days=2)}
    assert rows["khabarfoori"]["backfill_supported"] is True
    assert rows["shahrekhabar"]["backfill_supported"] is False
    assert rows["khabarfoori"]["missing_days"] == 2


# ------------------------------------------------------------- golden set and compare


def review_case(conn, *, url, status, category=None, scores=None, title="خبر آزمایشی درباره طلا"):
    article_id = store_article(conn, url, original_title=title, lead="لید", content="متن")
    db.insert(conn, "review_cases", {
        "article_id": article_id, "stratum": "test", "status": status,
        "reviewed_category": category, "created_at": "2026-01-01T00:00:00+03:30",
        **(scores or {}),
    })
    return article_id


def test_weighted_kappa_is_perfect_for_matching_ordinal_scores():
    assert reviews.weighted_kappa([1, 3, 5], [1, 3, 5]) == 1.0
    assert reviews.weighted_kappa([1], [1]) is None, "too few labels to compare"


def test_golden_set_is_built_only_from_approved_reviews(conn, tmp_path):
    """Pending and skipped rows carry no human judgement and must not become truth."""
    review_case(conn, url="https://test/approved", status="approved", category="economics")
    review_case(conn, url="https://test/pending", status="pending")
    review_case(conn, url="https://test/skipped", status="skipped")

    path = tmp_path / "golden.json"
    assert reviews.build_golden(conn, path) == 1
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert [case["article"]["url"] for case in cases] == ["https://test/approved"]


def test_an_axis_the_reviewer_left_unassessed_is_absent_not_defaulted(conn, tmp_path):
    """The legacy bug in miniature: an unjudged axis must contribute nothing at all."""
    review_case(conn, url="https://test/partial", status="approved", category="security",
                scores={"confidence_occurrence": "زیاد", "security_relevance": "خیلی زیاد"})
    path = tmp_path / "golden.json"
    reviews.build_golden(conn, path)
    scores = json.loads(path.read_text(encoding="utf-8"))[0]["scores"]
    assert scores == {"confidence_occurrence": "زیاد", "security_relevance": "خیلی زیاد"}


def test_the_built_golden_set_loads_back_and_scores_a_provider(conn, tmp_path):
    """Round trip: build_golden writes exactly what load_cases and evaluate() consume."""
    review_case(conn, url="https://test/roundtrip", status="approved",
                category="security/economics", title="حمله موشکی و اثر آن بر قیمت طلا",
                scores={"confidence_occurrence": "زیاد", "gold_price_impact": "زیاد",
                        "security_relevance": "زیاد"})
    path = tmp_path / "golden.json"
    reviews.build_golden(conn, path)
    cases = reviews.load_cases(path)
    assert len(cases) == 1 and cases[0].category == "security/economics"

    report = reviews.evaluate(cases, providers.RuleProvider())
    assert report["category_accuracy"] == 1.0
    assert report["kappa"]["gold_price_impact"] is None, "one case is not enough for kappa"


def test_an_empty_review_queue_produces_an_empty_set_rather_than_failing(conn, tmp_path):
    path = tmp_path / "golden.json"
    assert reviews.build_golden(conn, path) == 0
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_the_review_queue_exports_the_requested_cases(conn, article_id, tmp_path):
    db.insert(conn, "classifications", {
        "article_id": article_id, "category": "security", "confidence": "زیاد",
        "method": "legacy", "run_id": "legacy", "created_at": "2026-01-01T00:00:00+03:30",
    })
    assert reviews.create_queue(conn, size=1) == 1
    assert reviews.export_queue(conn, tmp_path / "review.xlsx").exists()


def inference(conn, article_id, *, version, category):
    for table, row in (
        ("classifications", {"category": category, "confidence": "زیاد", "method": "llm"}),
        ("evaluations", {"confidence_occurrence": "زیاد", "gold_price_impact": "زیاد",
                         "security_relevance": "زیاد", "gold_trend": "↑"}),
    ):
        db.insert(conn, table, {
            "article_id": article_id, "rationale": "r", "prompt_version": version,
            "provider": "gapgpt", "model": "m1", "run_id": "r1",
            "created_at": "2026-01-01T00:00:00", **row,
        })


def test_compare_splits_agreeing_and_diverging_articles_into_separate_files(conn, tmp_path):
    same = store_article(conn, "https://test/same", original_title="عنوان یک")
    different = store_article(conn, "https://test/diff", original_title="عنوان دو")
    for article_id in (same, different):
        inference(conn, article_id, version="va", category="security")
    inference(conn, same, version="vb", category="security")
    inference(conn, different, version="vb", category="economics")

    out_dir = tmp_path / "compare"
    summary = reviews.compare(conn, a=Variant("gapgpt", "m1", "va"),
                              b=Variant("gapgpt", "m1", "vb"), out_dir=out_dir)
    assert summary == {"shared_articles": 2, "same": 1, "different": 1, "out_dir": str(out_dir)}
    diff_text = (out_dir / "comparison_different.txt").read_text(encoding="utf-8")
    assert "category=security" in diff_text and "category=economics" in diff_text
    all_text = (out_dir / "comparison_all.txt").read_text(encoding="utf-8")
    assert all_text.count("same | ") == 1 and all_text.count("different | ") == 1


def test_compare_fails_loudly_when_a_variant_was_never_run(conn, tmp_path):
    with pytest.raises(ValueError):
        reviews.compare(conn, a=Variant("gapgpt", None, "va"),
                        b=Variant("gapgpt", None, "vb"), out_dir=tmp_path)


def test_compare_page_renders_a_real_diff_between_two_variants(client):
    with db.connect(client.db_path) as conn:
        article_id = conn.execute("SELECT id FROM articles").fetchone()["id"]
        for version, category in (("va", "security"), ("vb", "economics")):
            conn.execute(
                "INSERT INTO classifications(article_id,category,confidence,method,"
                "prompt_version,provider,model,run_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (article_id, category, "زیاد", "llm", version, "rule", "keyword-v1", "r",
                 "2026-01-01T00:00:00"))
        conn.commit()
    # A real <select>'s value goes through URL encoding, so build the request the same way
    # rather than embedding the raw \x1f separator in a URL string.
    body = client.get("/compare", params={"a": "rule\x1fkeyword-v1\x1fva",
                                          "b": "rule\x1fkeyword-v1\x1fvb"}).text
    # Category/level/trend values render through the same English labels as every other
    # page, not the raw stored vocabulary - see dashboard.py's category_label filter.
    assert "category: Security" in body and "category: Economics" in body
    assert "Disagreements (1)" in body


def test_compare_page_without_a_selection_shows_the_picker_only(client):
    assert "Choose two variants" in client.get("/compare").text


def test_compare_with_a_malformed_variant_shows_an_error_not_a_500(client):
    """A hand-edited query string used to raise ValueError past the try/except meant to
    catch it, turning a bad request into an unhandled 500."""
    response = client.get("/compare", params={"a": "not-enough-parts", "b": ""})
    assert response.status_code == 200 and "pill bad" in response.text
