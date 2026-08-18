"""The review page, exercised through real HTTP requests.

These cover the workflow a browser screenshot cannot assert: that the model's answer is
actually pre-selected, that "ارزیابی نشد" round-trips to NULL rather than a level, and
that the submitted label reaches every consumer of approved review data.
"""

import pytest

from news_intel import metrics, pipeline, providers
from news_intel.core import db
from news_intel.sources import RawArticle

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from news_intel import dashboard  # noqa: E402

ARTICLE = RawArticle(
    source="khabarfoori",
    url="https://example.test/gold",
    title="حمله موشکی به تاسیسات و جهش قیمت طلا در بازار تهران",
    lead="گزارش خبرگزاری از واکنش بازار",
    content="متن کامل خبر درباره حمله و اثر آن بر قیمت طلا و دلار در بازار داخلی امروز.",
    original_outlet="ایسنا",
    published_at="2026-08-16T10:00:00+03:30",
)


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "news.db"
    with db.init_db(path) as conn:
        pipeline.process(conn, [ARTICLE], providers.RuleProvider(), run_id="run1")
        article_id = conn.execute("SELECT id FROM articles").fetchone()["id"]
        db.insert(conn, "review_cases", {
            "article_id": article_id, "stratum": "security/economics",
            "created_at": "2026-08-16T10:00:00+03:30",
        })
    with TestClient(dashboard.create_app(path)) as test_client:
        test_client.db_path = path
        yield test_client


def review_row(client):
    with db.connect(client.db_path, readonly=True) as conn:
        return conn.execute("SELECT * FROM review_cases").fetchone()


# ------------------------------------------------------------------- pages


def test_every_page_renders(client):
    for route in ("/", "/review", "/kpi", "/ops", "/compare", "/partials/runs"):
        response = client.get(route)
        assert response.status_code == 200, f"{route} -> {response.status_code}"
        assert response.headers["content-type"].startswith("text/html")


def test_json_endpoints_answer(client):
    assert client.get("/api/kpi").json()["labelled"] == 0
    assert client.get("/api/health").json()["sources"] == []


def test_the_review_page_shows_the_article_a_reviewer_has_to_read(client):
    body = client.get("/review").text
    assert ARTICLE.title in body
    assert ARTICLE.content in body


def test_the_models_answer_is_pre_selected_on_the_form(client):
    """A reviewer corrects rather than fills; that is what makes the queue finishable."""
    body = client.get("/review").text
    # RuleProvider classifies this article as security/economics.
    assert 'value="security/economics" checked' in body.replace(" >", ">")


def test_kpi_shows_an_empty_state_rather_than_fabricated_numbers(client):
    assert "No approved labels recorded yet." in client.get("/kpi").text


def test_a_long_persian_url_is_shortened_in_the_link_text_but_not_in_the_href(tmp_path):
    """Percent-encoded Persian slugs run past 200 characters.

    Left alone they wrap over five lines and visually outweigh the article the reviewer
    is supposed to be reading. The href has to stay intact - only the label is cut.
    """
    slug = "%D8%A7%D9%82%D8%AA%D8%B5%D8%A7%D8%AF" * 8
    url = f"https://www.khabarfoori.com/{slug}"
    assert len(url) > 200

    path = tmp_path / "news.db"
    with db.init_db(path) as conn:
        pipeline.process(conn, [RawArticle(
            source="khabarfoori", url=url, title=ARTICLE.title,
            lead=ARTICLE.lead, content=ARTICLE.content,
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


# ------------------------------------------------------------------ submit


def test_submitting_a_label_stores_it_and_advances_the_queue(client):
    review_id = review_row(client)["id"]
    response = client.post(f"/review/{review_id}", data={
        "action": "approve",
        "reviewed_category": "security",
        "confidence_occurrence": "خیلی زیاد",
        "gold_price_impact": "کم",
        "security_relevance": "خیلی زیاد",
        "gold_trend": "↑",
        "one_line": "خلاصه بازبین",
        "reviewer_notes": "یادداشت",
    })
    assert response.status_code == 200  # followed the 303 back to /review

    row = review_row(client)
    assert row["status"] == "approved"
    assert row["reviewed_category"] == "security"
    assert row["confidence_occurrence"] == "خیلی زیاد"
    assert row["one_line"] == "خلاصه بازبین"
    assert row["reviewed_at"] is not None
    assert "Every case in the review queue has been reviewed." in client.get("/review").text


def test_an_unassessed_axis_is_stored_as_null_not_as_a_level(client):
    """The legacy suppression bug, at the point where a human could re-introduce it.

    The form posts an empty string for "ارزیابی نشد". If that were written as a level,
    or defaulted to the middle value, the notify floor would be computed from a judgement
    nobody made.
    """
    review_id = review_row(client)["id"]
    client.post(f"/review/{review_id}", data={
        "action": "approve",
        "reviewed_category": "security",
        "confidence_occurrence": "زیاد",
        "gold_price_impact": "",
        "security_relevance": "زیاد",
        "gold_trend": "",
    })
    row = review_row(client)
    assert row["gold_price_impact"] is None
    assert row["gold_trend"] is None
    assert db.level_score(row["gold_price_impact"]) is None


def test_approving_without_a_category_is_refused(client):
    review_id = review_row(client)["id"]
    response = client.post(f"/review/{review_id}", data={"action": "approve"})
    assert response.status_code == 400
    assert review_row(client)["status"] == "pending"


def test_skipping_records_no_label(client):
    review_id = review_row(client)["id"]
    client.post(f"/review/{review_id}", data={"action": "skip"})
    row = review_row(client)
    assert row["status"] == "skipped"
    assert row["reviewed_category"] is None


# --------------------------------------------------------------------- kpi


def test_an_approved_label_reaches_the_kpi_page(client):
    """One submission has to move every downstream number, not just the stored row."""
    review_id = review_row(client)["id"]
    client.post(f"/review/{review_id}", data={
        "action": "approve",
        "reviewed_category": "security",          # model said security/economics
        "confidence_occurrence": "زیاد",
        "gold_price_impact": "",
        "security_relevance": "زیاد",
    })

    payload = client.get("/api/kpi").json()
    assert payload["labelled"] == 1
    assert payload["pending"] == 0
    assert payload["category_accuracy"] == 0.0, "the human disagreed with the model"
    assert payload["confusion"]["security"]["security/economics"] == 1

    gold = next(a for a in payload["axes"] if a["axis"] == "gold_price_impact")
    assert gold["disagreed_on_presence"] == 1, "human left it unassessed, model did not"

    page = client.get("/kpi").text
    assert "No approved labels recorded yet." not in page
    assert "Category confusion matrix" in page


def test_the_label_becomes_a_few_shot_example_for_the_next_run(client):
    """The point of review: the next classification sees what a human decided."""
    from news_intel.reviews import reviewed_examples

    review_id = review_row(client)["id"]
    client.post(f"/review/{review_id}", data={
        "action": "approve", "reviewed_category": "security",
        "confidence_occurrence": "زیاد", "security_relevance": "زیاد",
    })
    with db.connect(client.db_path, readonly=True) as conn:
        examples = reviewed_examples(conn, ARTICLE, task="classify")
    assert [example.category for example in examples] == ["security"]


def test_the_dashboard_cannot_lock_the_database_it_monitors(client):
    """Monitoring reads through a read-only connection; a writer stays unblocked."""
    with db.connect(client.db_path) as writer:
        client.get("/kpi")
        writer.execute("INSERT INTO sources(name,tier) VALUES('probe',1)")
        writer.commit()
    assert any(s["name"] == "probe" for s in client.get("/api/health").json()["sources"])


def test_metrics_and_the_json_api_agree(client):
    review_id = review_row(client)["id"]
    client.post(f"/review/{review_id}", data={
        "action": "approve", "reviewed_category": "economics",
        "confidence_occurrence": "کم", "gold_price_impact": "کم",
    })
    with db.connect(client.db_path, readonly=True) as conn:
        report = metrics.compute(conn)
    assert client.get("/api/kpi").json()["macro_f1"] == report.macro_f1


# ---------------------------------------------------------------------- home


def test_home_lists_notify_worthy_news_in_english_chrome_with_persian_content(client):
    """RuleProvider classifies ARTICLE as security/economics with three high axes -
    a real notify case, not a fabricated fixture."""
    body = client.get("/").text
    assert ARTICLE.title in body  # article content itself stays Persian
    assert "Rolling window" in body  # surrounding chrome is English
    assert '<html lang="en">' in body


def test_saving_the_window_setting_persists_and_redirects_home(client):
    response = client.post("/settings/window", data={"days": "30"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"
    with db.connect(client.db_path, readonly=True) as conn:
        assert db.get_setting(conn, "rolling_window_days", "14") == "30"


# ----------------------------------------------------------------------- ops


def test_ops_page_shows_the_funnel_and_source_health(client):
    with db.connect(client.db_path) as conn:
        conn.execute(
            "INSERT INTO sources(name,tier,config_path,priority,enabled,health_status)"
            " VALUES('khabarfoori',2,'x',1,1,'healthy')"
        )
        conn.commit()
    body = client.get("/ops").text
    assert "Pipeline Ops" in body
    assert "khabarfoori" in body  # from the source health table


def test_api_telemetry_returns_the_four_aggregations(client):
    payload = client.get("/api/telemetry?days=7").json()
    assert set(payload) == {
        "token_cost_by_day", "node_status_counts", "provider_breakdown", "fetch_volume_by_source",
    }
    assert payload["fetch_volume_by_source"][0]["source"] == "khabarfoori"


# ------------------------------------------------------------------- compare


def test_compare_page_without_a_selection_shows_the_picker_only(client):
    body = client.get("/compare").text
    assert "Choose two variants" in body


def test_compare_page_renders_a_real_diff_between_two_variants(client):
    with db.connect(client.db_path) as conn:
        article_id = conn.execute("SELECT id FROM articles").fetchone()["id"]
        for version, category in (("va", "security"), ("vb", "economics")):
            conn.execute(
                "INSERT INTO classifications(article_id,category,confidence,method,"
                "prompt_version,provider,model,run_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (article_id, category, "زیاد", "llm", version, "rule", "keyword-v1", "r", "2026-01-01T00:00:00"),
            )
        conn.commit()
    a = "rule\x1fkeyword-v1\x1fva"
    b = "rule\x1fkeyword-v1\x1fvb"
    # A real <select>'s submitted value goes through form/URL percent-encoding, so build
    # the request the same way rather than embedding the raw control char in a URL string.
    body = client.get("/compare", params={"a": a, "b": b}).text
    assert "category: security" in body and "category: economics" in body
    assert "Disagreements (1)" in body
