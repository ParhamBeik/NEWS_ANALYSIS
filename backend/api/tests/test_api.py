"""API contract tests.

Four things are worth locking here, and they are the four that would rot silently:

1. **Auth fails closed.** A forgotten permission class serves the corpus to the internet.
2. **No N+1.** A feed card reads three append-only relations. Losing a `Prefetch` does not
   break a test that only checks the payload - it just makes the page slow in production,
   at exactly the corpus size where nobody is watching.
3. **The A/B pair stays blind.** If variant identity leaks into the response, every
   judgement collected afterwards is contaminated and cannot be un-contaminated.
4. **The notify filter agrees with `decide`.** There must be exactly one notify rule; this
   test is what proves the filter did not become a second one.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from core.scoring import decide
from core.vocabulary import Category, GoldTrend, Level, NotifyStatus
from inference.models import Classification, Evaluation, PromptVariant, Summary
from review.models import ABFeedback, ABPair, ReviewCase, ReviewStatus, Side


@pytest.fixture
def client(user) -> APIClient:
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def classify(article, variant, category=Category.SECURITY, **kwargs):
    return Classification.objects.create(
        article=article, variant=variant, category=category,
        confidence=Level.HIGH, prompt_version="ptest", provider="gapgpt",
        model=variant.model, **kwargs,
    )


def evaluate(article, variant, **scores):
    fields = {
        "confidence_occurrence": Level.HIGH,
        "gold_price_impact": None,
        "security_relevance": Level.VERY_HIGH,
        "gold_trend": GoldTrend.UNCERTAIN,
    }
    fields.update(scores)
    return Evaluation.objects.create(
        article=article, variant=variant, prompt_version="ptest",
        provider="gapgpt", model=variant.model, **fields,
    )


class TestAuthentication:
    def test_health_is_public(self):
        """The container healthcheck and the edge proxy hit this before any login exists."""
        assert APIClient().get("/api/health/").status_code == 200

    def test_signup_creates_a_regular_user_and_returns_a_working_token(self, db):
        api = APIClient()
        response = api.post(
            "/api/auth/signup/",
            {"username": "new-analyst", "email": "analyst@example.com", "password": "Mango-River-47-Orbit"},
            format="json",
        )
        assert response.status_code == 201
        user = get_user_model().objects.get(username="new-analyst")
        assert not user.is_staff and not user.is_superuser
        api.credentials(HTTP_AUTHORIZATION=f"Token {response.json()['token']}")
        assert api.get("/api/auth/me/").status_code == 200

    def test_signup_rejects_weak_passwords(self, db):
        response = APIClient().post(
            "/api/auth/signup/",
            {"username": "weak-user", "password": "password"},
            format="json",
        )
        assert response.status_code == 400
        assert not get_user_model().objects.filter(username="weak-user").exists()

    @pytest.mark.parametrize(
        "path",
        ["/api/articles/", "/api/ops/", "/api/kpi/", "/api/market/",
         "/api/exports/", "/api/ab/pairs/", "/api/reviews/", "/api/sources/"],
    )
    def test_everything_else_requires_login(self, db, path):
        assert APIClient().get(path).status_code in {401, 403}


class TestFeed:
    def test_card_carries_the_persian_value_and_an_english_label(
        self, client, article, variant
    ):
        """The stored value must survive the round trip unchanged - it is the only string
        the team's Excel dropdown accepts. The English gloss rides alongside, never
        instead."""
        evaluate(article, variant)
        row = client.get("/api/articles/").json()["results"][0]
        assert row["scores"]["security_relevance"]["value"] == "خیلی زیاد"
        assert "Very high" in row["scores"]["security_relevance"]["label"]

    def test_an_unassessed_axis_is_null_not_a_level(self, client, article, variant):
        """Frozen invariant 2/4, at the API boundary.

        Serialising an unassessed axis as "" or as a low level is the exact substitution
        that made the notify floor unreachable and suppressed every security alert.
        """
        evaluate(article, variant, gold_price_impact=None)
        row = client.get("/api/articles/").json()["results"][0]
        assert row["scores"]["gold_price_impact"] is None

    def test_the_notify_reason_is_exposed(self, client, article, variant):
        """A reviewer needs to know WHY, not just what. "only 1 strong axes" is auditable;
        a bare boolean is not."""
        evaluate(article, variant)
        row = client.get("/api/articles/").json()["results"][0]
        assert row["decision"]["reason"]

    def test_duplicates_are_hidden_by_default_and_countable_on_request(
        self, client, make_article
    ):
        canonical = make_article()
        make_article(duplicate_of=canonical, duplicate_score=0.9)
        assert client.get("/api/articles/").json()["count"] == 1
        assert client.get("/api/articles/?include_duplicates=true").json()["count"] == 2

    def test_summary_title_wins_over_the_original(self, client, article, variant):
        Summary.objects.create(
            article=article, variant=variant, optimized_title="تیتر بهینه",
            one_line="خلاصه", prompt_version="ptest", provider="gapgpt", model=variant.model,
        )
        assert client.get("/api/articles/").json()["results"][0]["title"] == "تیتر بهینه"

    def test_the_newest_answer_wins_not_the_first(self, client, article, variant):
        """Inference is append-only, so "the" classification is the latest one. Reading any
        other row would show a verdict a later run already replaced."""
        classify(article, variant, category=Category.OTHER)
        classify(article, variant, category=Category.SECURITY)
        assert client.get("/api/articles/").json()["results"][0]["category"] == "security"


class TestNoNPlusOne:
    def test_feed_query_count_does_not_grow_with_the_page(
        self, client, django_assert_max_num_queries, make_article, variant
    ):
        """The regression test for a dropped `Prefetch`.

        Twenty articles, each with three append-only relations, is 60 extra queries if the
        prefetches are lost - and the response body is byte-identical either way, so no
        assertion on content would ever catch it.
        """
        for _ in range(20):
            article = make_article()
            classify(article, variant)
            evaluate(article, variant)
            Summary.objects.create(
                article=article, variant=variant, optimized_title="ت", one_line="خ",
                prompt_version="ptest", provider="gapgpt", model=variant.model,
            )
        with django_assert_max_num_queries(12):
            response = client.get("/api/articles/?limit=20")
        assert len(response.json()["results"]) == 20


class TestNotifyFilterMatchesTheRule:
    def test_the_sql_filter_returns_exactly_what_decide_returns(
        self, client, make_article, variant
    ):
        """One notify rule, not two.

        Every combination below is scored by `decide` in Python and then requested through
        the API. If the filter ever grows its own copy of the thresholds, these diverge.
        """
        combinations = [
            (Level.VERY_HIGH, Level.HIGH, Level.HIGH),
            (Level.HIGH, None, Level.VERY_HIGH),
            (Level.LOW, Level.HIGH, Level.HIGH),
            (Level.MEDIUM, Level.MEDIUM, None),
            (Level.VERY_LOW, Level.VERY_HIGH, Level.VERY_HIGH),
        ]
        expected: dict[str, set[int]] = {value: set() for value in NotifyStatus.values}
        for confidence, gold, security in combinations:
            article = make_article()
            evaluate(
                article, variant, confidence_occurrence=confidence,
                gold_price_impact=gold, security_relevance=security,
            )
            expected[decide(confidence, gold, security).status].add(article.id)

        for state, ids in expected.items():
            rows = client.get(f"/api/articles/?notify={state}").json()["results"]
            assert {row["id"] for row in rows} == ids, f"filter disagrees with decide on {state}"

    def test_a_null_axis_does_not_block_notification(self, client, make_article, variant):
        """The counterpart to the sentinel bug, end to end.

        Two strong axes with the third NULL must notify. Legacy filled that third axis with
        «خیلی کم», which put the minimum below the floor and turned this exact case into
        silence - 0 of 488 alerts. The DB constraint makes INSUFFICIENT unreachable from a
        stored evaluation, so this is the strongest form the case can take.
        """
        article = make_article()
        evaluate(
            article, variant, confidence_occurrence=Level.HIGH,
            gold_price_impact=Level.HIGH, security_relevance=None,
        )
        assert client.get(f"/api/articles/?notify={NotifyStatus.NOTIFY}").json()["count"] == 1


class TestABBlinding:
    @pytest.fixture
    def pair(self, db, article, variant):
        challenger = PromptVariant.objects.create(
            name="semantic-memory", model="gemini-3.1-flash-lite",
            memory_strategy="semantic", memory_k=5,
        )
        for arm in (variant, challenger):
            classify(article, arm)
            evaluate(article, arm)
        return ABPair.objects.create(
            article=article, variant_a=variant, variant_b=challenger, shown_as_left=Side.B,
        )

    def test_the_response_never_names_the_variants(self, client, pair):
        """THE test for this feature.

        A leaked model name biases every judgement collected afterwards, and there is no
        way to clean that out of the data later - you can only throw the judgements away.
        """
        payload = client.get("/api/ab/pairs/next/").content.decode()
        assert "shown_as_left" not in payload
        assert pair.variant_a.name not in payload
        assert pair.variant_b.name not in payload
        assert pair.variant_b.model not in payload

    def test_both_sides_carry_the_reasoning_being_judged(self, client, pair):
        body = client.get("/api/ab/pairs/next/").json()
        for side in ("left", "right"):
            assert body[side]["scores"] is not None
            assert body[side]["decision"]["reason"]

    def test_the_winner_resolves_to_the_variant_that_held_that_position(self, client, pair):
        """`shown_as_left=B` means the left card was variant_b. Storing the raw position
        and resolving it server-side is what makes position bias measurable at all."""
        response = client.post(f"/api/ab/pairs/{pair.id}/feedback/", {"winner": "left"})
        assert response.status_code == 201
        assert ABFeedback.objects.get().winning_variant == pair.variant_b
        # Unblinded only AFTER the judgement is stored.
        assert response.json()["revealed"]["chosen"] == pair.variant_b.name

    def test_a_second_submission_edits_rather_than_double_votes(self, client, pair):
        client.post(f"/api/ab/pairs/{pair.id}/feedback/", {"winner": "left"})
        client.post(f"/api/ab/pairs/{pair.id}/feedback/", {"winner": "tie", "reasoning": "same"})
        record = ABFeedback.objects.get()
        assert record.winner == "tie"
        assert record.winning_variant is None

    def test_a_judged_pair_is_not_served_again_to_the_same_user(self, client, pair):
        client.post(f"/api/ab/pairs/{pair.id}/feedback/", {"winner": "right"})
        assert client.get("/api/ab/pairs/next/").status_code == 204

    def test_results_report_position_bias(self, client, pair):
        client.post(f"/api/ab/pairs/{pair.id}/feedback/", {"winner": "left"})
        body = client.get("/api/ab/pairs/results/").json()
        assert body["position_bias"]["left_share_of_decided"] == 1.0
        assert body["standings"][0]["variant"] == pair.variant_b.name

    def test_an_invalid_winner_is_rejected(self, client, pair):
        response = client.post(f"/api/ab/pairs/{pair.id}/feedback/", {"winner": "middle"})
        assert response.status_code == 400


class TestReview:
    @pytest.fixture
    def case(self, db, article, variant):
        classify(article, variant)
        evaluate(article, variant)
        return ReviewCase.objects.create(article=article, stratum="disagreement")

    def test_the_form_is_prefilled_with_the_models_own_answer(self, client, case):
        """Correcting is faster and more consistent than filling a blank form, and it makes
        a disagreement a deliberate act rather than an omission."""
        body = client.get("/api/reviews/next/").json()
        assert body["model_answer"]["category"] == Category.SECURITY
        assert body["model_answer"]["security_relevance"] == Level.VERY_HIGH

    def test_a_blank_axis_is_stored_as_null(self, client, case):
        """The mirror of the feed test, on the ground-truth side. A sentinel written here
        would corrupt the labels the model is measured against - worse than a bad
        prediction, because it is permanent."""
        response = client.post(
            f"/api/reviews/{case.id}/submit/",
            {"reviewed_category": Category.SECURITY,
             "confidence_occurrence": Level.HIGH,
             "gold_price_impact": "",
             "security_relevance": Level.HIGH},
        )
        assert response.status_code == 200
        case.refresh_from_db()
        assert case.gold_price_impact is None
        assert case.status == ReviewStatus.APPROVED
        assert case.reviewed_at is not None

    def test_an_invented_level_is_rejected(self, client, case):
        response = client.post(
            f"/api/reviews/{case.id}/submit/",
            {"reviewed_category": Category.SECURITY, "confidence_occurrence": "HIGH"},
        )
        assert response.status_code == 400

    def test_the_reviewer_is_recorded(self, client, case, user):
        client.post(
            f"/api/reviews/{case.id}/submit/",
            {"reviewed_category": Category.OTHER},
        )
        case.refresh_from_db()
        assert case.reviewer == user

    def test_a_submitted_case_leaves_the_queue(self, client, case):
        client.post(f"/api/reviews/{case.id}/submit/", {"reviewed_category": Category.OTHER})
        assert client.get("/api/reviews/next/").status_code == 204

    def test_skipping_is_recorded_rather_than_discarded(self, client, case):
        """An article a human could not label is not one the model should be scored
        against, so the skip has to be a stored fact."""
        client.post(f"/api/reviews/{case.id}/skip/", {"reviewer_notes": "ambiguous"})
        case.refresh_from_db()
        assert case.status == ReviewStatus.SKIPPED
        assert not case.is_usable_truth


class TestKPI:
    def test_agreement_ignores_axes_the_human_left_blank(self, client, article, variant):
        """Counting a blank human field as a disagreement would punish the model for the
        reviewer's omission and make the metric drift with reviewer fatigue."""
        evaluate(article, variant)
        ReviewCase.objects.create(
            article=article, stratum="round_robin", status=ReviewStatus.APPROVED,
            reviewed_category=Category.SECURITY,
            confidence_occurrence=Level.HIGH,
            gold_price_impact=None,
            security_relevance=Level.VERY_HIGH,
            reviewed_at=timezone.now(),
        )
        classify(article, variant)
        body = client.get("/api/kpi/").json()
        by_axis = {row["axis"]: row for row in body["axis_agreement"]}
        assert by_axis["gold_price_impact"]["compared"] == 0
        assert by_axis["security_relevance"]["exact_rate"] == 1.0
        assert body["category_agreement"]["rate"] == 1.0

    def test_adjacent_levels_count_as_near_agreement(self, client, article, variant):
        """The scale is ordinal. «زیاد» vs «خیلی زیاد» is a far smaller error than «زیاد»
        vs «خیلی کم», and an exact-match-only metric hides that difference entirely."""
        evaluate(article, variant, security_relevance=Level.VERY_HIGH)
        ReviewCase.objects.create(
            article=article, stratum="round_robin", status=ReviewStatus.APPROVED,
            reviewed_category=Category.SECURITY,
            confidence_occurrence=Level.HIGH, security_relevance=Level.HIGH,
            reviewed_at=timezone.now(),
        )
        by_axis = {
            row["axis"]: row for row in client.get("/api/kpi/").json()["axis_agreement"]
        }
        assert by_axis["security_relevance"]["exact_rate"] == 0.0
        assert by_axis["security_relevance"]["within_one_rate"] == 1.0

    def test_unapproved_labels_are_not_treated_as_truth(self, client, article, variant):
        """A golden set seeded from pending rows would measure the model against itself."""
        evaluate(article, variant)
        ReviewCase.objects.create(
            article=article, stratum="round_robin", reviewed_category=Category.OTHER
        )
        assert client.get("/api/kpi/").json()["labelled_articles"] == 0


class TestExports:
    def test_a_traversing_filename_cannot_escape_the_export_directory(
        self, client, settings, tmp_path
    ):
        """`../../.env` is a perfectly valid-looking filename. Resolve, then confirm
        containment - a regex on the segment is not an adequate defence."""
        settings.EXPORT_DIR = tmp_path
        (tmp_path.parent / "secret.txt").write_text("do not serve me")
        assert client.get("/api/exports/..%2Fsecret.txt/").status_code == 404
        assert client.get("/api/exports/../secret.txt/").status_code == 404

    def test_a_real_export_downloads(self, client, settings, tmp_path):
        settings.EXPORT_DIR = tmp_path
        (tmp_path / "report.xlsx").write_bytes(b"PK\x03\x04stub")
        listing = client.get("/api/exports/").json()
        assert listing[0]["name"] == "report.xlsx"
        assert client.get("/api/exports/report.xlsx/").status_code == 200

    def test_the_listing_reaches_into_the_exporters_subdirectories(
        self, client, settings, tmp_path
    ):
        """`export_all` writes workbooks to `Excel Files/` and feeds to `TXT Files/`.

        A flat listing showed the one loose file at the top level and silently omitted the
        nightly workbook - the product of the whole pipeline - from the only page that
        offers it, while reporting success.
        """
        settings.EXPORT_DIR = tmp_path
        (tmp_path / "important_news.txt").write_text("feed")
        (tmp_path / "Excel Files").mkdir()
        (tmp_path / "Excel Files" / "ثبت و تحلیل خبر - 11 شهریور 1405.xlsx").write_bytes(
            b"PK\x03\x04stub"
        )
        listing = client.get("/api/exports/").json()
        names = {entry["name"] for entry in listing}
        assert "important_news.txt" in names
        assert "Excel Files/ثبت و تحلیل خبر - 11 شهریور 1405.xlsx" in names

        workbook = next(entry for entry in listing if entry["name"].startswith("Excel"))
        assert client.get(workbook["download_url"]).status_code == 200


class TestOps:
    def test_the_funnel_and_the_budget_are_reported_together(self, client, make_article):
        """Throughput without spend is the number that lets a runaway run look healthy."""
        canonical = make_article()
        make_article(duplicate_of=canonical, duplicate_score=0.88)
        make_article(prefilter_reason="sports_desk")
        body = client.get("/api/ops/").json()
        assert body["funnel"]["fetched"] == 3
        assert body["funnel"]["duplicates"] == 1
        assert body["funnel"]["prefiltered"] == 1
        assert body["budget"]["daily_ceiling_usd"] > 0

    def test_source_health_is_included(self, client, source):
        assert client.get("/api/ops/").json()["sources"][0]["name"] == source.name

    def test_the_notify_counts_respect_the_window_and_the_canonical_filter(
        self, client, make_article, variant
    ):
        """Every other number in this response is windowed; the notify counts were not.

        `articles_with_decision` scans the latest evaluation of the whole corpus, so the
        feed page rendered an all-time, duplicate-inclusive total in a row labelled
        "(24h)" - a figure that only ever grew and never described the last day.
        """
        recent = make_article()
        evaluate(recent, variant)
        duplicate = make_article(duplicate_of=recent, duplicate_score=0.9)
        evaluate(duplicate, variant)
        older = make_article(fetched_at=timezone.now() - timedelta(days=5))
        evaluate(older, variant)

        assert client.get("/api/ops/?days=1").json()["notify"][NotifyStatus.NOTIFY] == 1
        assert client.get("/api/ops/?days=30").json()["notify"][NotifyStatus.NOTIFY] == 2


def test_the_feeds_verdict_filter_offers_only_values_the_filter_accepts():
    """A contract between the two halves of the repo, because nothing else checks it.

    `notify` is a ChoiceFilter, so a value the backend does not have is not a filter that
    quietly matches nothing - it is a 400, and the feed page renders its error boundary
    instead of the feed. The frontend shipped «اطلاعات ناکافی» against the vocabulary's
    «ارزیابی ناکافی»: three characters apart, invisible in review, and the "Insufficient"
    option was broken from the day it was written.
    """
    page = Path(settings.BASE_DIR).parent / "frontend" / "app" / "page.js"
    if not page.exists():
        pytest.skip("frontend tree not present (backend-only image)")
    offered = re.findall(
        r'\["([^"]+)",\s*"(?:Notify|Quiet|Insufficient)"\]', page.read_text(encoding="utf-8")
    )
    assert offered, "the feed's NOTIFY_STATES list moved; this test needs to follow it"
    assert offered == list(NotifyStatus.values)


@pytest.mark.django_db
def test_token_auth_works_for_a_server_side_fetch():
    """Next.js server components fetch with a header, not a browser cookie - a session
    would simply not be attached, and every server-rendered page would 403."""
    user = get_user_model().objects.create_user("nextjs", password="pw")
    api = APIClient()
    token = api.post("/api/auth/token/", {"username": "nextjs", "password": "pw"}).json()
    assert "token" in token
    api.credentials(HTTP_AUTHORIZATION=f"Token {token['token']}")
    assert api.get("/api/auth/me/").json()["username"] == user.username
