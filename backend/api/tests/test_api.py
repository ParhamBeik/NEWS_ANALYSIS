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

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from api.filters import articles_with_decision
from core.scoring import decide
from core.vocabulary import Category, GoldTrend, Level, NotifyStatus
from inference.models import Classification, Evaluation, PromptVariant, Summary
from review.models import ABFeedback, ABPair, ReviewCase, ReviewStatus, Side


@pytest.fixture
def client(user) -> APIClient:
    api = APIClient()
    api.force_authenticate(user=user)
    return api


@pytest.fixture
def staff_client(user) -> APIClient:
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    api = APIClient()
    api.force_authenticate(user=user)
    return api


@pytest.fixture
def throttle_rates(monkeypatch):
    """Set a throttle rate for the duration of one test.

    Not `settings.REST_FRAMEWORK`: DRF binds `THROTTLE_RATES` onto the throttle class at
    IMPORT time, so overriding the setting afterwards changes nothing and the test passes
    against a limit that was never applied. The class attribute is the live value.
    """
    from api.views import LoginThrottle, SignupThrottle

    def _apply(**rates):
        for throttle in (LoginThrottle, SignupThrottle):
            monkeypatch.setattr(throttle, "THROTTLE_RATES", {**throttle.THROTTLE_RATES, **rates})

    return _apply


def classify(article, variant, category=Category.SECURITY, **kwargs):
    return Classification.objects.create(
        article=article,
        variant=variant,
        category=category,
        confidence=Level.HIGH,
        prompt_version="ptest",
        provider="gapgpt",
        model=variant.model,
        **kwargs,
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
        article=article,
        variant=variant,
        prompt_version="ptest",
        provider="gapgpt",
        model=variant.model,
        **fields,
    )


class TestAuthentication:
    def test_health_is_public(self, db):
        """The container healthcheck and the edge proxy hit this before any login exists."""
        assert APIClient().get("/api/health/").status_code == 200

    def test_health_reports_a_dependency_outage(self, monkeypatch):
        def unavailable(_key):
            raise OSError("redis is unavailable")

        monkeypatch.setattr("api.views.cache.get", unavailable)
        response = APIClient().get("/api/health/")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}

    def test_signup_creates_a_regular_user_and_returns_a_working_token(self, db):
        api = APIClient()
        response = api.post(
            "/api/auth/signup/",
            {
                "username": "new-analyst",
                "email": "analyst@example.com",
                "password": "Mango-River-47-Orbit",
            },
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

    def test_signup_turns_a_concurrent_username_claim_into_a_field_error(self, db, monkeypatch):
        from django.db import IntegrityError

        def already_claimed(_serializer):
            raise IntegrityError("duplicate key")

        monkeypatch.setattr("api.views.SignupSerializer.save", already_claimed)
        response = APIClient().post(
            "/api/auth/signup/",
            {"username": "racing-user", "password": "Mango-River-47-Orbit"},
            format="json",
        )
        assert response.status_code == 400
        assert response.json() == {"username": "This username is already in use."}

    @pytest.mark.parametrize(
        "path",
        [
            "/api/articles/",
            "/api/feed-stats/",
            "/api/ops/",
            "/api/kpi/",
            "/api/market/",
            "/api/exports/",
            "/api/ab/pairs/",
            "/api/reviews/",
            "/api/sources/",
        ],
    )
    def test_everything_else_requires_login(self, db, path):
        assert APIClient().get(path).status_code in {401, 403}

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/api/ab/pairs/next/"),
            ("get", "/api/ab/pairs/results/"),
            ("post", "/api/ab/pairs/1/feedback/"),
            ("get", "/api/reviews/next/"),
            ("post", "/api/reviews/1/submit/"),
            ("post", "/api/reviews/1/skip/"),
        ],
    )
    def test_shared_evaluation_workflows_require_staff(self, client, method, path):
        """A public signup must never be able to alter shared training evidence."""
        assert getattr(client, method)(path, {}, format="json").status_code == 403

    def test_empty_login_credentials_return_field_errors(self, db):
        response = APIClient().post(
            "/api/auth/token/",
            {"username": "", "password": ""},
            format="json",
        )
        assert response.status_code == 400
        body = response.json()
        assert "username" in body or "password" in body or "non_field_errors" in body

    def test_password_guessing_is_rate_limited(self, db, user, throttle_rates):
        """The login endpoint is the only place a stranger learns whether a password is
        right. Unthrottled, every account is worth exactly one online brute-force run."""
        throttle_rates(login="3/min")
        api = APIClient()
        attempt = {"username": user.get_username(), "password": "not-the-password"}
        codes = [api.post("/api/auth/token/", attempt, format="json").status_code for _ in range(4)]
        assert codes[:3] == [400, 400, 400], codes
        assert codes[3] == 429, "the fourth guess should have been throttled"

    def test_a_forged_forwarded_header_does_not_buy_a_fresh_allowance(
        self, db, user, settings, throttle_rates
    ):
        """Behind the edge, the throttle identity comes from X-Forwarded-For - which the
        CLIENT can also send. DRF's default reads the whole header, so a caller inventing a
        new value per request gets a new bucket per request and the limit stops existing.
        NUM_PROXIES pins the identity to the last hop, the one Caddy itself appended."""
        settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
        throttle_rates(login="2/min")
        api = APIClient()
        attempt = {"username": user.get_username(), "password": "not-the-password"}
        codes = [
            api.post(
                "/api/auth/token/",
                attempt,
                format="json",
                # A different forged prefix each time; the real peer is the trailing entry.
                HTTP_X_FORWARDED_FOR=f"10.0.0.{n}, 203.0.113.7",
            ).status_code
            for n in range(3)
        ]
        assert codes == [400, 400, 429], codes

    def test_account_creation_is_rate_limited(self, db, throttle_rates):
        """Registration is open, so the only thing standing between a stranger and an
        unbounded number of user rows is this limit."""
        throttle_rates(signup="2/hour")
        api = APIClient()
        codes = [
            api.post(
                "/api/auth/signup/",
                {"username": f"flood-{n}", "password": "Mango-River-47-Orbit"},
                format="json",
            ).status_code
            for n in range(3)
        ]
        assert codes == [201, 201, 429], codes
        assert get_user_model().objects.filter(username__startswith="flood-").count() == 2

    def test_signing_out_revokes_the_token_rather_than_just_the_cookie(self, db, user):
        """A DRF token never expires. If sign-out only drops the browser cookie, the string
        it held stays a working credential for the whole corpus forever."""
        api = APIClient()
        token = api.post(
            "/api/auth/token/",
            {"username": user.get_username(), "password": "test-pass"},
            format="json",
        ).json()["token"]

        api.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        assert api.get("/api/auth/me/").status_code == 200
        assert api.post("/api/auth/logout/").status_code == 204
        assert api.get("/api/auth/me/").status_code == 401

    def test_a_valid_token_cannot_bypass_signup_throttling(self, db, user, throttle_rates):
        from rest_framework.authtoken.models import Token

        throttle_rates(signup="1/hour")
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=user).key}")
        codes = [
            api.post(
                "/api/auth/signup/",
                {
                    "username": f"extra-{n}",
                    "password": "Mango-River-47-Orbit",
                },
                format="json",
            ).status_code
            for n in range(2)
        ]
        assert codes == [201, 429]

    def test_signing_out_twice_is_not_an_error(self, db, user):
        api = APIClient()
        api.force_authenticate(user=user)
        assert api.post("/api/auth/logout/").status_code == 204
        assert api.post("/api/auth/logout/").status_code == 204


class TestFeed:
    def test_card_carries_the_persian_value_and_an_english_label(self, client, article, variant):
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

    def test_duplicates_are_hidden_by_default_and_countable_on_request(self, client, make_article):
        canonical = make_article()
        make_article(duplicate_of=canonical, duplicate_score=0.9)
        assert client.get("/api/articles/").json()["count"] == 1
        assert client.get("/api/articles/?include_duplicates=true").json()["count"] == 2

    def test_summary_title_wins_over_the_original(self, client, article, variant):
        Summary.objects.create(
            article=article,
            variant=variant,
            optimized_title="تیتر بهینه",
            one_line="خلاصه",
            prompt_version="ptest",
            provider="gapgpt",
            model=variant.model,
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
                article=article,
                variant=variant,
                optimized_title="ت",
                one_line="خ",
                prompt_version="ptest",
                provider="gapgpt",
                model=variant.model,
            )
        with django_assert_max_num_queries(12):
            response = client.get("/api/articles/?limit=20")
        assert len(response.json()["results"]) == 20

    def test_review_queue_query_count_does_not_grow_with_the_page(
        self, staff_client, django_assert_max_num_queries, make_article, variant
    ):
        """The review list prefetches the same three relations the feed does, and then the
        serializer has to actually READ them.

        `get_model_answer` reached for `article.classifications.first()`. A `Prefetch` with
        `to_attr` does not populate the related manager, so every one of those went back to
        the database - three per case, plus one more for `duplicates` - which made the
        viewset's prefetches pure cost with none of the benefit. Same shape as the feed
        regression above, one layer further in, and equally invisible in the payload.
        """
        for _ in range(20):
            article = make_article()
            classify(article, variant)
            evaluate(article, variant)
            Summary.objects.create(
                article=article,
                variant=variant,
                optimized_title="ت",
                one_line="خ",
                prompt_version="ptest",
                provider="gapgpt",
                model=variant.model,
            )
            ReviewCase.objects.create(article=article, stratum="round_robin")
        # Six today. The bound is what matters, not the number: a regression here is
        # 80 extra queries on this page, not one.
        with django_assert_max_num_queries(8):
            response = staff_client.get("/api/reviews/?limit=20")
        assert len(response.json()["results"]) == 20


class TestNotifyFilterMatchesTheRule:
    def test_scoped_decision_only_considers_requested_articles(self, make_article, variant):
        inside = make_article()
        outside = make_article()
        evaluate(inside, variant)
        evaluate(outside, variant)

        assert articles_with_decision(NotifyStatus.NOTIFY, {inside.id}) == {inside.id}

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
                article,
                variant,
                confidence_occurrence=confidence,
                gold_price_impact=gold,
                security_relevance=security,
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
            article,
            variant,
            confidence_occurrence=Level.HIGH,
            gold_price_impact=Level.HIGH,
            security_relevance=None,
        )
        assert client.get(f"/api/articles/?notify={NotifyStatus.NOTIFY}").json()["count"] == 1


class TestABBlinding:
    @pytest.fixture
    def pair(self, db, article, variant):
        challenger = PromptVariant.objects.create(
            name="semantic-memory",
            model="gemini-3.1-flash-lite",
            memory_strategy="semantic",
            memory_k=5,
        )
        for arm in (variant, challenger):
            classify(article, arm)
            evaluate(article, arm)
        return ABPair.objects.create(
            article=article,
            variant_a=variant,
            variant_b=challenger,
            shown_as_left=Side.B,
        )

    def test_the_response_never_names_the_variants(self, staff_client, pair):
        """THE test for this feature.

        A leaked model name biases every judgement collected afterwards, and there is no
        way to clean that out of the data later - you can only throw the judgements away.
        """
        payload = staff_client.get("/api/ab/pairs/next/").content.decode()
        assert "shown_as_left" not in payload
        assert pair.variant_a.name not in payload
        assert pair.variant_b.name not in payload
        assert pair.variant_b.model not in payload

    def test_both_sides_carry_the_reasoning_being_judged(self, staff_client, pair):
        body = staff_client.get("/api/ab/pairs/next/").json()
        for side in ("left", "right"):
            assert body[side]["scores"] is not None
            assert body[side]["decision"]["reason"]

    def test_the_winner_resolves_to_the_variant_that_held_that_position(
        self, staff_client, pair
    ):
        """`shown_as_left=B` means the left card was variant_b. Storing the raw position
        and resolving it server-side is what makes position bias measurable at all."""
        response = staff_client.post(f"/api/ab/pairs/{pair.id}/feedback/", {"winner": "left"})
        assert response.status_code == 201
        assert ABFeedback.objects.get().winning_variant == pair.variant_b
        # Unblinded only AFTER the judgement is stored.
        assert response.json()["revealed"]["chosen"] == pair.variant_b.name

    def test_a_second_submission_edits_rather_than_double_votes(self, staff_client, pair):
        staff_client.post(f"/api/ab/pairs/{pair.id}/feedback/", {"winner": "left"})
        staff_client.post(
            f"/api/ab/pairs/{pair.id}/feedback/", {"winner": "tie", "reasoning": "same"}
        )
        record = ABFeedback.objects.get()
        assert record.winner == "tie"
        assert record.winning_variant is None

    def test_a_judged_pair_is_not_served_again_to_the_same_user(self, staff_client, pair):
        staff_client.post(f"/api/ab/pairs/{pair.id}/feedback/", {"winner": "right"})
        assert staff_client.get("/api/ab/pairs/next/").status_code == 204

    def test_results_report_position_bias(self, staff_client, pair):
        staff_client.post(f"/api/ab/pairs/{pair.id}/feedback/", {"winner": "left"})
        body = staff_client.get("/api/ab/pairs/results/").json()
        assert body["position_bias"]["left_share_of_decided"] == 1.0
        assert body["standings"][0]["variant"] == pair.variant_b.name

    def test_an_invalid_winner_is_rejected(self, staff_client, pair):
        response = staff_client.post(
            f"/api/ab/pairs/{pair.id}/feedback/", {"winner": "middle"}
        )
        assert response.status_code == 400


class TestReview:
    @pytest.fixture
    def case(self, db, article, variant):
        classify(article, variant)
        evaluate(article, variant)
        return ReviewCase.objects.create(article=article, stratum="disagreement")

    def test_the_form_is_prefilled_with_the_models_own_answer(self, staff_client, case):
        """Correcting is faster and more consistent than filling a blank form, and it makes
        a disagreement a deliberate act rather than an omission."""
        body = staff_client.get("/api/reviews/next/").json()
        assert body["model_answer"]["category"] == Category.SECURITY
        assert body["model_answer"]["security_relevance"] == Level.VERY_HIGH

    def test_a_blank_axis_is_stored_as_null(self, staff_client, case):
        """The mirror of the feed test, on the ground-truth side. A sentinel written here
        would corrupt the labels the model is measured against - worse than a bad
        prediction, because it is permanent."""
        response = staff_client.post(
            f"/api/reviews/{case.id}/submit/",
            {
                "reviewed_category": Category.SECURITY,
                "confidence_occurrence": Level.HIGH,
                "gold_price_impact": "",
                "security_relevance": Level.HIGH,
            },
        )
        assert response.status_code == 200
        case.refresh_from_db()
        assert case.gold_price_impact is None
        assert case.status == ReviewStatus.APPROVED
        assert case.reviewed_at is not None

    def test_an_invented_level_is_rejected(self, staff_client, case):
        response = staff_client.post(
            f"/api/reviews/{case.id}/submit/",
            {"reviewed_category": Category.SECURITY, "confidence_occurrence": "HIGH"},
        )
        assert response.status_code == 400

    def test_the_reviewer_is_recorded(self, staff_client, case, user):
        staff_client.post(
            f"/api/reviews/{case.id}/submit/",
            {"reviewed_category": Category.OTHER},
        )
        case.refresh_from_db()
        assert case.reviewer == user

    def test_a_submitted_case_leaves_the_queue(self, staff_client, case):
        staff_client.post(
            f"/api/reviews/{case.id}/submit/", {"reviewed_category": Category.OTHER}
        )
        assert staff_client.get("/api/reviews/next/").status_code == 204

    def test_skipping_is_recorded_rather_than_discarded(self, staff_client, case):
        """An article a human could not label is not one the model should be scored
        against, so the skip has to be a stored fact."""
        staff_client.post(f"/api/reviews/{case.id}/skip/", {"reviewer_notes": "ambiguous"})
        case.refresh_from_db()
        assert case.status == ReviewStatus.SKIPPED
        assert not case.is_usable_truth


class TestKPI:
    def test_agreement_ignores_axes_the_human_left_blank(self, client, article, variant):
        """Counting a blank human field as a disagreement would punish the model for the
        reviewer's omission and make the metric drift with reviewer fatigue."""
        evaluate(article, variant)
        ReviewCase.objects.create(
            article=article,
            stratum="round_robin",
            status=ReviewStatus.APPROVED,
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
            article=article,
            stratum="round_robin",
            status=ReviewStatus.APPROVED,
            reviewed_category=Category.SECURITY,
            confidence_occurrence=Level.HIGH,
            security_relevance=Level.HIGH,
            reviewed_at=timezone.now(),
        )
        by_axis = {row["axis"]: row for row in client.get("/api/kpi/").json()["axis_agreement"]}
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

    def test_a_missing_backup_directory_reports_unconfigured_rather_than_erroring(
        self, client, settings, tmp_path
    ):
        """A deployment without the backup volume mounted must still render /ops. An
        exception here would take the whole operational dashboard down over a missing
        directory, which is the moment you most need the dashboard."""
        settings.BACKUP_DIR = tmp_path / "nowhere"
        backups = client.get("/api/ops/").json()["backups"]
        assert backups == {
            "configured": False,
            "last_success_at": None,
            "age_hours": None,
            "retained": 0,
        }

    def test_backup_age_comes_from_an_existing_archive(self, client, settings, tmp_path):
        import os

        dump = tmp_path / "newsintel-20260908-030000.dump"
        dump.write_bytes(b"PGDMP")
        two_days_ago = (timezone.now() - timedelta(days=2)).timestamp()
        os.utime(dump, (two_days_ago, two_days_ago))
        # Neither a fresh success marker nor an in-progress dump makes the old dump fresh.
        (tmp_path / ".last-success").write_text("2026-09-08T03:00:00Z")
        (tmp_path / "incomplete.dump.partial").write_bytes(b"partial")
        (tmp_path / "empty.dump").touch()
        settings.BACKUP_DIR = tmp_path

        backups = client.get("/api/ops/").json()["backups"]
        assert backups["configured"] is True
        assert backups["retained"] == 1
        assert backups["age_hours"] == 48.0

        dump.unlink()
        backups = client.get("/api/ops/").json()["backups"]
        assert backups["age_hours"] is None
        assert backups["retained"] == 0


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
