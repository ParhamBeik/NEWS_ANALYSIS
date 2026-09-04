"""The API the frontend consumes.

Read paths are viewsets; the dashboards (`/ops`, `/kpi`, `/market`) are plain APIViews that
return one purpose-built document each. Splitting a dashboard into six generic endpoints
would mean six round trips to render one screen, and every one of them would need the same
window filter applied consistently by the client.

Three rules hold everywhere:

- Every list view names its prefetches. A feed card reads the latest classification,
  evaluation and summary; without an explicit `Prefetch` that is 90 extra queries per page
  (an N+1, three times over).
- Nothing derives the notify decision except `core.scoring.decide`. See api/filters.py.
- `ABPair.shown_as_left` and the variant ids never leave the server on an unjudged pair.
"""

from __future__ import annotations

import mimetypes
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Avg, Count, DecimalField, Prefetch, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from articles.models import Article
from core.vocabulary import AXES, NotifyStatus
from inference import budget
from inference.models import (
    Classification,
    DeadLetter,
    Evaluation,
    NodeEvent,
    PromptVariant,
    Run,
    Summary,
)
from market.models import PredictionOutcome, PriceSnapshot, Symbol
from review.models import ABFeedback, ABPair, ReviewCase, ReviewStatus, Winner
from sources.models import PrefilterRule, Source

from .filters import ArticleFilter, articles_with_decision
from .serializers import (
    ABPairSerializer,
    ArticleDetailSerializer,
    ArticleListSerializer,
    PredictionOutcomeSerializer,
    PriceSnapshotSerializer,
    ReviewCaseSerializer,
    ReviewSubmitSerializer,
    RunSerializer,
    SignupSerializer,
    SourceSerializer,
    VariantSerializer,
)

DEFAULT_WINDOW_DAYS = 14


def window_start(request, default_days: int = DEFAULT_WINDOW_DAYS):
    try:
        days = int(request.query_params.get("days", default_days))
    except ValueError as exc:
        raise ValidationError({"days": "must be an integer"}) from exc
    return timezone.now() - timedelta(days=max(1, min(days, 365)))


def latest_inference_prefetches(prefix: str = "") -> list[Prefetch]:
    """One row per article per result type, resolved in three extra queries total.

    `latest_ids()` is a DISTINCT ON subquery, so this prefetches exactly the newest answer
    rather than every historical one - which matters because inference is append-only and
    an article re-run under five variants has five of each.

    `prefix` is for querysets rooted somewhere other than Article (a ReviewCase needs
    "article__classifications"); `to_attr` stays unprefixed because it lands on the Article
    instance either way, which is where the serializer looks for it.
    """
    return [
        Prefetch(
            f"{prefix}classifications",
            queryset=Classification.objects.filter(pk__in=Classification.objects.latest_ids()),
            to_attr="latest_classification",
        ),
        Prefetch(
            f"{prefix}evaluations",
            queryset=Evaluation.objects.filter(pk__in=Evaluation.objects.latest_ids()),
            to_attr="latest_evaluation",
        ),
        Prefetch(
            f"{prefix}summaries",
            queryset=Summary.objects.filter(pk__in=Summary.objects.latest_ids()),
            to_attr="latest_summary",
        ),
    ]


class HealthView(APIView):
    """Unauthenticated on purpose: this is what the container healthcheck and Caddy hit."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok"})


class MeView(APIView):
    def get(self, request):
        return Response({
            "username": request.user.get_username(),
            "is_staff": request.user.is_staff,
        })


class SignupThrottle(AnonRateThrottle):
    rate = "5/hour"


class SignupView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [SignupThrottle]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token = Token.objects.create(user=user)
        return Response({"token": token.key, "username": user.get_username()}, status=201)


class ArticleViewSet(viewsets.ReadOnlyModelViewSet):
    filterset_class = ArticleFilter

    def get_serializer_class(self):
        return ArticleDetailSerializer if self.action == "retrieve" else ArticleListSerializer

    def get_queryset(self):
        queryset = (
            Article.objects.select_related("source", "image")
            .prefetch_related(*latest_inference_prefetches())
        )
        # Canonical-only by default. See the note in api/filters.py for why this is not a
        # FilterSet field: an absent parameter has to narrow, and django-filter cannot.
        if self.request.query_params.get("include_duplicates", "").lower() not in {"1", "true"}:
            queryset = queryset.filter(duplicate_of__isnull=True)
        if self.action == "retrieve":
            queryset = queryset.prefetch_related("duplicates")
        return queryset

    @action(detail=True, methods=["get"])
    def similar(self, request, pk=None):
        """The retrieved memory that shaped this article's verdict, exactly as the model
        saw it - same function, same variant, same k.

        Reconstructing it with a separate query here would show a plausible-looking set of
        neighbours that is not the one the model actually received, which is worse than
        showing nothing. A retrieval layer you cannot inspect is one you cannot debug.
        """
        from inference.memory import retrieve

        article = self.get_object()
        classification = (getattr(article, "latest_classification", None) or [None])[0]
        variant = (
            (classification.variant if classification else None)
            or PromptVariant.objects.filter(is_active=True).first()
        )
        if variant is None:
            return Response([])
        neighbours = retrieve(
            article,
            variant,
            task=request.query_params.get("task", "evaluation"),
            category=classification.category if classification else None,
        )
        return Response([
            {
                "title": item.title,
                "category": item.category,
                "similarity": round(item.similarity, 4),
                # True = a human approved this label; False = it is the model's own past
                # verdict. Feeding a model its own output back is a real failure mode, so
                # the distinction is surfaced rather than smoothed over.
                "reviewed": item.reviewed,
                "output": item.output,
            }
            for item in neighbours
        ])


class SourceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Source.objects.all()
    serializer_class = SourceSerializer
    lookup_field = "name"


class RunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Run.objects.all()
    serializer_class = RunSerializer
    lookup_field = "run_id"

    @action(detail=True, methods=["get"])
    def events(self, request, run_id=None):
        run = self.get_object()
        rows = run.events.select_related("article")[:500]
        return Response([
            {
                "node": event.node, "status": event.status, "attempt": event.attempt,
                "article_id": event.article_id, "latency_ms": event.latency_ms,
                "cost_usd": float(event.cost_usd), "error_class": event.error_class,
                "error": event.error[:400], "created_at": event.created_at,
            }
            for event in rows
        ])


class VariantViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PromptVariant.objects.all()
    serializer_class = VariantSerializer


# ------------------------------------------------------------------------------- review


class ReviewViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ReviewCaseSerializer

    def get_queryset(self):
        queryset = ReviewCase.objects.select_related(
            "article", "article__source", "article__image"
        ).prefetch_related(*latest_inference_prefetches("article__"))
        if state := self.request.query_params.get("status"):
            queryset = queryset.filter(status=state)
        return queryset

    @action(detail=False, methods=["get"])
    def next(self, request):
        """The labelling queue's head. Returns 204 when the queue is empty, so the client
        can distinguish "nothing to do" from "request failed"."""
        case = self.get_queryset().filter(status=ReviewStatus.PENDING).first()
        if case is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(self.get_serializer(case).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        case = self.get_object()
        form = ReviewSubmitSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        for field, value in form.validated_data.items():
            setattr(case, field, value)
        case.status = ReviewStatus.APPROVED
        case.reviewer = request.user
        case.reviewed_at = timezone.now()
        case.save()
        return Response(ReviewCaseSerializer(case, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def skip(self, request, pk=None):
        """Skipping is data too: an article a human could not label is not one the model
        should be scored against."""
        case = self.get_object()
        case.status = ReviewStatus.SKIPPED
        case.reviewer = request.user
        case.reviewed_at = timezone.now()
        case.reviewer_notes = request.data.get("reviewer_notes", "")
        case.save()
        return Response({"status": case.status})


# ---------------------------------------------------------------------------------- a/b


class ABPairViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ABPairSerializer

    def get_queryset(self):
        return ABPair.objects.select_related("article", "variant_a", "variant_b")

    @action(detail=False, methods=["get"])
    def next(self, request):
        """The next pair THIS user has not judged.

        Filtering per user rather than globally: two reviewers judging the same pair is
        signal (it measures inter-rater agreement), not a duplicate to be suppressed.
        """
        pair = (
            self.get_queryset()
            .exclude(feedback__user=request.user)
            .order_by("?")
            .first()
        )
        if pair is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(self.get_serializer(pair).data)

    @action(detail=True, methods=["post"])
    def feedback(self, request, pk=None):
        pair = self.get_object()
        winner = request.data.get("winner")
        if winner not in Winner.values:
            raise ValidationError({"winner": f"must be one of {Winner.values}"})
        record, _ = ABFeedback.objects.update_or_create(
            pair=pair,
            user=request.user,
            defaults={"winner": winner, "reasoning": request.data.get("reasoning", "")},
        )
        # The unblinding happens only AFTER the judgement is stored, so the reviewer can
        # see what they chose without that knowledge having influenced the choice.
        chosen = record.winning_variant
        return Response(
            {
                "saved": True,
                "winner": record.winner,
                "revealed": {
                    "left": pair.variant_on(Winner.LEFT).name,
                    "right": pair.variant_on(Winner.RIGHT).name,
                    "chosen": chosen.name if chosen else None,
                },
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["get"])
    def results(self, request):
        """Aggregate standings, plus the position-bias check.

        Reporting wins without position bias would be dishonest: if a reviewer picks the
        left card 70% of the time regardless of content, the standings measure layout, not
        quality. Storing `shown_as_left` is what makes that number computable at all.
        """
        rows = ABFeedback.objects.select_related(
            "pair", "pair__variant_a", "pair__variant_b"
        )
        tally: dict[str, dict] = {}
        left_wins = right_wins = ties = 0
        for record in rows:
            if record.winner == Winner.LEFT:
                left_wins += 1
            elif record.winner == Winner.RIGHT:
                right_wins += 1
            else:
                ties += 1
            for variant in (record.pair.variant_a, record.pair.variant_b):
                tally.setdefault(
                    variant.name,
                    {"variant": variant.name, "model": variant.model,
                     "memory_strategy": variant.memory_strategy,
                     "appearances": 0, "wins": 0, "ties": 0},
                )
                tally[variant.name]["appearances"] += 1
            chosen = record.winning_variant
            if chosen is None:
                for variant in (record.pair.variant_a, record.pair.variant_b):
                    tally[variant.name]["ties"] += 1
            else:
                tally[chosen.name]["wins"] += 1

        standings = sorted(
            (
                {**entry, "win_rate": round(entry["wins"] / entry["appearances"], 3)}
                for entry in tally.values() if entry["appearances"]
            ),
            key=lambda entry: entry["win_rate"],
            reverse=True,
        )
        decided = left_wins + right_wins
        return Response({
            "judgements": rows.count(),
            "standings": standings,
            "position_bias": {
                "left_wins": left_wins, "right_wins": right_wins, "ties": ties,
                # 0.5 is unbiased. Far from it means the layout is being judged.
                "left_share_of_decided": round(left_wins / decided, 3) if decided else None,
            },
            "pairs_awaiting_judgement": ABPair.objects.exclude(
                feedback__user=request.user
            ).count(),
        })


# ---------------------------------------------------------------------------- dashboards


class OpsView(APIView):
    """The operational picture: what the pipeline did, what it cost, what broke."""

    def get(self, request):
        since = window_start(request)
        events = NodeEvent.objects.filter(created_at__gte=since)
        articles = Article.objects.filter(fetched_at__gte=since)
        # `articles_with_decision` scans the LATEST evaluation of every article ever
        # stored, so the notify counts have to be intersected back down to this window and
        # to canonical rows. Without it the feed page renders an all-time, duplicate-
        # inclusive total in a row labelled "(24h)", and it only ever grows.
        canonical_ids = set(
            articles.filter(duplicate_of__isnull=True).values_list("id", flat=True)
        )

        by_node = list(
            events.values("node", "status")
            .annotate(count=Count("id"), cost=Sum("cost_usd"))
            .order_by("node", "status")
        )
        cost_by_day = list(
            events.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(
                cost=Coalesce(Sum("cost_usd"), 0, output_field=DecimalField()),
                calls=Count("id"),
            )
            .order_by("day")
        )
        return Response({
            "window_days": (timezone.now() - since).days,
            "funnel": {
                "fetched": articles.count(),
                "canonical": articles.filter(duplicate_of__isnull=True).count(),
                "duplicates": articles.filter(duplicate_of__isnull=False).count(),
                "prefiltered": articles.exclude(prefilter_reason="").count(),
                "quality_rejected": articles.exclude(quality_flag="").count(),
                "classified": articles.filter(classifications__isnull=False).distinct().count(),
                "evaluated": articles.filter(evaluations__isnull=False).distinct().count(),
            },
            "notify": {
                state: len(articles_with_decision(state) & canonical_ids)
                for state in NotifyStatus.values
            },
            "extraction_tiers": list(
                articles.values("extraction_tier").annotate(count=Count("id")).order_by()
            ),
            "node_outcomes": [
                {**row, "cost": float(row["cost"] or 0)} for row in by_node
            ],
            "cost_by_day": [
                {"day": row["day"], "cost": float(row["cost"]), "calls": row["calls"]}
                for row in cost_by_day
            ],
            "budget": {
                "run_ceiling_usd": settings.NEWS_RUN_BUDGET_USD,
                "daily_ceiling_usd": settings.NEWS_DAILY_BUDGET_USD,
                "spent_today_usd": budget.day_spend(),
            },
            "sources": SourceSerializer(Source.objects.all(), many=True).data,
            # The prefilter is the one change that can silently lose a story, so its
            # effect is reported rather than assumed. `articles` is the evidence you would
            # need to justify turning a rule off again.
            "prefilter_rules": [
                {
                    "source": rule.source_id, "native_category": rule.native_category,
                    "label": rule.label, "enabled": rule.enabled, "note": rule.note,
                    "articles": Article.objects.filter(
                        source_id=rule.source_id, native_category=rule.native_category
                    ).count(),
                }
                for rule in PrefilterRule.objects.select_related("source")
            ],
            "images": list(
                Article.objects.values("image__status").annotate(count=Count("id")).order_by()
            ),
            "dead_letters": list(
                DeadLetter.objects.filter(resolved_at__isnull=True)
                .values("node", "error_class")
                .annotate(count=Count("id"))
                .order_by("-count")
            ),
            "recent_runs": RunSerializer(Run.objects.all()[:10], many=True).data,
        })


class KPIView(APIView):
    """Quality, not throughput: does the model agree with a human, and was it right about
    the gold price?"""

    def get(self, request):
        labelled = list(
            ReviewCase.objects.filter(status=ReviewStatus.APPROVED)
            .exclude(reviewed_category="")
            .select_related("article")
            .prefetch_related(*latest_inference_prefetches("article__"))
        )

        category_hits = category_total = 0
        axis_stats = {axis: {"compared": 0, "exact": 0, "within_one": 0} for axis in AXES}
        notify_confusion = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
        per_stratum: dict[str, dict] = {}

        from core.scoring import decide, level_score

        for case in labelled:
            classification = (getattr(case.article, "latest_classification", None) or [None])[0]
            evaluation = (getattr(case.article, "latest_evaluation", None) or [None])[0]
            bucket = per_stratum.setdefault(
                case.stratum, {"stratum": case.stratum, "compared": 0, "agreed": 0}
            )
            if classification:
                category_total += 1
                bucket["compared"] += 1
                if classification.category == case.reviewed_category:
                    category_hits += 1
                    bucket["agreed"] += 1
            if not evaluation:
                continue
            for axis in AXES:
                human, machine = getattr(case, axis), getattr(evaluation, axis)
                # Only compare where BOTH assessed. Counting "human said nothing" as a
                # disagreement would punish the model for the reviewer's blank field.
                if human is None or machine is None:
                    continue
                axis_stats[axis]["compared"] += 1
                axis_stats[axis]["exact"] += human == machine
                # Adjacent agreement matters on an ordinal scale: «زیاد» vs «خیلی زیاد» is
                # a far smaller error than «زیاد» vs «خیلی کم», and exact-match hides that.
                axis_stats[axis]["within_one"] += (
                    abs(level_score(human) - level_score(machine)) <= 1
                )
            human_notify = decide(
                case.confidence_occurrence, case.gold_price_impact, case.security_relevance
            ).notify
            machine_notify = evaluation.decision.notify
            key = {(True, True): "tp", (False, True): "fp",
                   (False, False): "tn", (True, False): "fn"}[(human_notify, machine_notify)]
            notify_confusion[key] += 1

        outcomes = PredictionOutcome.objects.exclude(direction_correct__isnull=True)
        scored = outcomes.count()
        return Response({
            "labelled_articles": len(labelled),
            "category_agreement": {
                "compared": category_total,
                "agreed": category_hits,
                "rate": round(category_hits / category_total, 3) if category_total else None,
            },
            "agreement_by_stratum": [
                {**row, "rate": round(row["agreed"] / row["compared"], 3)}
                for row in per_stratum.values() if row["compared"]
            ],
            "axis_agreement": [
                {
                    "axis": axis,
                    **stats,
                    "exact_rate": round(stats["exact"] / stats["compared"], 3)
                    if stats["compared"] else None,
                    "within_one_rate": round(stats["within_one"] / stats["compared"], 3)
                    if stats["compared"] else None,
                }
                for axis, stats in axis_stats.items()
            ],
            "notify_confusion": notify_confusion,
            # A false negative is a missed security alert - the exact failure this rebuild
            # exists to prevent - so it is reported on its own, not buried in an accuracy
            # figure that a mostly-quiet corpus would inflate.
            "notify_recall": (
                round(
                    notify_confusion["tp"] / (notify_confusion["tp"] + notify_confusion["fn"]), 3
                )
                if (notify_confusion["tp"] + notify_confusion["fn"]) else None
            ),
            "backtest": {
                "scored_predictions": scored,
                "directional_accuracy": round(
                    outcomes.filter(direction_correct=True).count() / scored, 3
                ) if scored else None,
                "mean_realized_pct": outcomes.aggregate(v=Avg("realized_pct"))["v"],
                "by_window": list(
                    outcomes.values("window_trading_days")
                    .annotate(
                        n=Count("id"),
                        correct=Count("id", filter=Q(direction_correct=True)),
                    )
                    .order_by("window_trading_days")
                ),
                "unscored_neutral": PredictionOutcome.objects.filter(
                    direction_correct__isnull=True
                ).count(),
            },
        })


class MarketView(APIView):
    def get(self, request):
        since = window_start(request, 30)
        symbol = request.query_params.get("symbol", Symbol.GOLD_18K)
        if symbol not in Symbol.values:
            raise ValidationError({"symbol": f"must be one of {Symbol.values}"})
        series = PriceSnapshot.objects.filter(
            symbol=symbol, observed_at__gte=since
        ).order_by("observed_at")
        outcomes = (
            PredictionOutcome.objects.filter(computed_at__gte=since)
            .select_related("evaluation")
            .order_by("-computed_at")[:200]
        )
        return Response({
            "symbol": symbol,
            "symbols": [{"value": value, "label": label} for value, label in Symbol.choices],
            "series": PriceSnapshotSerializer(series, many=True).data,
            "latest": PriceSnapshotSerializer(
                PriceSnapshot.objects.filter(symbol=symbol).order_by("-observed_at").first()
            ).data if series.exists() else None,
            "outcomes": PredictionOutcomeSerializer(outcomes, many=True).data,
        })


class ExportListView(APIView):
    """Workbooks are files on a volume, not rows. Listing the directory keeps the exporter
    free to write whatever it writes without a second source of truth to keep in sync.

    RECURSIVE, because the exporter writes into subdirectories the team already files by:
    the workbooks land in `Excel Files/` and the category feeds in `TXT Files/`. A flat
    `iterdir()` listed the one loose file at the top level and silently omitted the nightly
    workbook - the product of the entire pipeline - from the only page that offers it.
    """

    def get(self, request):
        directory = Path(settings.EXPORT_DIR)
        if not directory.exists():
            return Response([])
        files = sorted(
            (path for path in directory.rglob("*") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return Response([
            {
                # Relative to EXPORT_DIR, so the subdirectory is part of the name and the
                # download URL round-trips through the `<path:name>` route unchanged.
                "name": path.relative_to(directory).as_posix(),
                "size_bytes": path.stat().st_size,
                "modified_at": timezone.datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.get_current_timezone()
                ),
                # Relative for the same reason media URLs are: the caller may be a server
                # component that reached this API on an internal hostname.
                "download_url": f"/api/exports/{path.relative_to(directory).as_posix()}/",
            }
            for path in files
        ])


class ExportDownloadView(APIView):
    def get(self, request, name: str):
        directory = Path(settings.EXPORT_DIR).resolve()
        # Resolve first, then confirm containment. Trusting the URL segment here would be a
        # path traversal: `../../.env` is a perfectly valid-looking filename.
        target = (directory / name).resolve()
        if not target.is_file() or directory not in target.parents:
            raise Http404("no such export")
        content_type, _ = mimetypes.guess_type(target.name)
        return FileResponse(
            target.open("rb"),
            as_attachment=True,
            filename=target.name,
            content_type=content_type or "application/octet-stream",
        )
