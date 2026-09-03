"""Serializers.

Two rules run through all of these:

1. Persian VALUES are sent through unchanged, and English labels ride alongside. The
   frontend shows «زیاد» with an English gloss; the stored value stays the exact string the
   team's Excel dropdown accepts. Translating at the API boundary would mean translating
   back before export, and one of those two mappings would eventually drift.

2. An unassessed axis serialises as `null`, never as "" or "not assessed". The whole
   pipeline exists because a sentinel in that position suppressed every security alert, and
   the API is the easiest place to reintroduce one by accident.
"""

from __future__ import annotations

from rest_framework import serializers

from articles.models import Article, ArticleImage
from core.vocabulary import AXES, Category, GoldTrend, Level, NotifyStatus
from inference.models import Classification, Evaluation, PromptVariant, Run, Summary
from market.models import PredictionOutcome, PriceSnapshot
from review.models import ABFeedback, ABPair, ReviewCase
from sources.models import Source

# One place to build the English gloss for a Persian value, so every endpoint agrees.
LEVEL_LABELS = dict(Level.choices)
TREND_LABELS = dict(GoldTrend.choices)


def labelled(value: str | None, labels: dict[str, str]) -> dict | None:
    """`{"value": "زیاد", "label": "High (زیاد)"}`, or null when unassessed."""
    return {"value": value, "label": labels.get(value, value)} if value else None


class SourceSerializer(serializers.ModelSerializer):
    supports_backfill = serializers.BooleanField(read_only=True)

    class Meta:
        model = Source
        fields = [
            "name", "display_name", "strategy", "url", "tier", "priority", "enabled",
            "health_status", "last_success_at", "last_error", "supports_backfill",
        ]


class ArticleImageSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()

    class Meta:
        model = ArticleImage
        fields = ["file", "thumbnail", "width", "height", "status"]

    def _url(self, field):
        """A RELATIVE path, deliberately.

        `build_absolute_uri` would return the origin the API was reached on - which, for a
        Next.js server component, is the internal `http://backend:8000`. The browser cannot
        resolve that. A relative `/media/...` is served from whatever origin the page is on:
        Caddy in production, the Next dev rewrite locally.

        This is also what "images from the VPS" means in practice - the file is downloaded
        during the crawl and served from our own domain, so a browser never fetches from an
        Iranian CDN that may not answer it.
        """
        return field.url if field else None

    def get_file(self, obj):
        return self._url(obj.file)

    def get_thumbnail(self, obj):
        return self._url(obj.thumbnail)


class ClassificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Classification
        fields = [
            "category", "confidence", "rationale", "matched_keywords",
            "provider", "model", "prompt_version", "created_at",
        ]


class EvaluationSerializer(serializers.ModelSerializer):
    """Scores plus the notify decision, with the reason the rule gave."""

    scores = serializers.SerializerMethodField()
    gold_trend = serializers.SerializerMethodField()
    decision = serializers.SerializerMethodField()

    class Meta:
        model = Evaluation
        fields = [
            "scores", "gold_trend", "decision", "rationale",
            "provider", "model", "prompt_version", "created_at",
        ]

    def get_scores(self, obj):
        return {axis: labelled(getattr(obj, axis), LEVEL_LABELS) for axis in AXES}

    def get_gold_trend(self, obj):
        return labelled(obj.gold_trend, TREND_LABELS)

    def get_decision(self, obj):
        outcome = obj.decision
        return {
            "status": outcome.status,
            "label": dict(NotifyStatus.choices).get(outcome.status, outcome.status),
            "notify": outcome.notify,
            # The reason string is shown in the UI. "only 1 strong axes" is far more useful
            # to a reviewer than a bare "not notified", and it is what makes the rule
            # auditable rather than opaque.
            "reason": outcome.reason,
            "axes_assessed": outcome.assessed,
            "strong_axes": outcome.high,
        }


class SummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Summary
        fields = ["optimized_title", "one_line", "provider", "model", "created_at"]


class ArticleListSerializer(serializers.ModelSerializer):
    """The feed card. Deliberately thin - no body text, no rationales."""

    image = ArticleImageSerializer(read_only=True)
    source = serializers.CharField(source="source_id")
    outlet = serializers.CharField(source="original_outlet")
    title = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    scores = serializers.SerializerMethodField()
    decision = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = [
            "id", "url", "source", "outlet", "title", "lead", "image",
            "published_at", "published_at_jalali", "published_time", "date_uncertain",
            "extraction_tier", "native_category", "keywords",
            # On the CARD, not just the detail page: an analysed-looking article with no
            # scores needs to say why on the spot, or it reads as a pipeline failure.
            "prefilter_reason", "quality_flag",
            "category", "scores", "decision",
        ]

    def _latest(self, obj, attr):
        """Prefetched by the viewset; falling back to a query here would be an N+1 on a
        30-card page."""
        rows = getattr(obj, attr, None)
        return rows[0] if rows else None

    def get_title(self, obj):
        summary = self._latest(obj, "latest_summary")
        return (summary.optimized_title if summary else "") or obj.original_title

    def get_category(self, obj):
        classification = self._latest(obj, "latest_classification")
        return classification.category if classification else None

    def get_scores(self, obj):
        evaluation = self._latest(obj, "latest_evaluation")
        if evaluation is None:
            return None
        return {
            **{axis: labelled(getattr(evaluation, axis), LEVEL_LABELS) for axis in AXES},
            "gold_trend": labelled(evaluation.gold_trend, TREND_LABELS),
        }

    def get_decision(self, obj):
        evaluation = self._latest(obj, "latest_evaluation")
        if evaluation is None:
            return None
        outcome = evaluation.decision
        return {"status": outcome.status, "notify": outcome.notify, "reason": outcome.reason}


class ArticleDetailSerializer(ArticleListSerializer):
    """Everything behind a card, including WHY the model decided what it did."""

    classification = serializers.SerializerMethodField()
    evaluation = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    duplicates = serializers.SerializerMethodField()

    class Meta(ArticleListSerializer.Meta):
        fields = [
            *ArticleListSerializer.Meta.fields,
            "content", "original_title", "content_hash", "fetched_at",
            "classification", "evaluation", "summary", "duplicates",
        ]

    def get_classification(self, obj):
        row = self._latest(obj, "latest_classification")
        return ClassificationSerializer(row).data if row else None

    def get_evaluation(self, obj):
        row = self._latest(obj, "latest_evaluation")
        return EvaluationSerializer(row).data if row else None

    def get_summary(self, obj):
        row = self._latest(obj, "latest_summary")
        return SummarySerializer(row).data if row else None

    def get_duplicates(self, obj):
        """The other copies of this story. Shown so a reviewer can see the dedup decision
        rather than wondering where a headline went."""
        return [
            {"id": dup.id, "source": dup.source_id, "url": dup.url,
             "title": dup.original_title, "score": dup.duplicate_score}
            for dup in obj.duplicates.all()
        ]


# ------------------------------------------------------------------------------- review


class ReviewCaseSerializer(serializers.ModelSerializer):
    """The labelling form, pre-filled with the model's own answer.

    Pre-filling matters: a reviewer who CORRECTS is far faster and more consistent than one
    who fills a blank form, and disagreements become deliberate rather than accidental.
    """

    article = serializers.SerializerMethodField()
    model_answer = serializers.SerializerMethodField()

    class Meta:
        model = ReviewCase
        fields = [
            "id", "stratum", "status", "article", "model_answer",
            "reviewed_category", *AXES, "gold_trend", "one_line", "reviewer_notes",
        ]

    def get_article(self, obj):
        return ArticleDetailSerializer(obj.article, context=self.context).data

    def get_model_answer(self, obj):
        classification = obj.article.classifications.first()
        evaluation = obj.article.evaluations.first()
        summary = obj.article.summaries.first()
        return {
            "category": classification.category if classification else None,
            "rationale": classification.rationale if classification else None,
            **{axis: getattr(evaluation, axis, None) for axis in AXES},
            "gold_trend": evaluation.gold_trend if evaluation else None,
            "one_line": summary.one_line if summary else None,
        }


class ReviewSubmitSerializer(serializers.Serializer):
    """A submitted label.

    Every score field is `allow_null` and defaults to None. A blank field means "not
    assessed" and MUST land as NULL - writing a level there would poison the ground truth
    the model is measured against with the very sentinel this system exists to prevent.
    """

    reviewed_category = serializers.ChoiceField(choices=Category.choices)
    confidence_occurrence = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    gold_price_impact = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    security_relevance = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    gold_trend = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    one_line = serializers.CharField(required=False, allow_blank=True, default="")
    reviewer_notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        for axis in AXES:
            value = attrs.get(axis) or None
            if value and value not in LEVEL_LABELS:
                raise serializers.ValidationError({axis: f"unknown level {value!r}"})
            attrs[axis] = value
        trend = attrs.get("gold_trend") or None
        if trend and trend not in TREND_LABELS:
            raise serializers.ValidationError({"gold_trend": f"unknown trend {trend!r}"})
        attrs["gold_trend"] = trend
        return attrs


# ---------------------------------------------------------------------------------- a/b


class VariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromptVariant
        fields = [
            "id", "name", "description", "provider", "model",
            "memory_strategy", "memory_k", "prompt_version", "is_active",
        ]


class ABPairSerializer(serializers.ModelSerializer):
    """A blinded head-to-head.

    `shown_as_left` and the variant ids are NEVER serialised. The reviewer sees "left" and
    "right" with no model names - so the judgement cannot be biased by knowing which arm is
    the expensive one, and position bias stays measurable afterwards because the mapping is
    still stored server-side.
    """

    article = serializers.SerializerMethodField()
    left = serializers.SerializerMethodField()
    right = serializers.SerializerMethodField()

    class Meta:
        model = ABPair
        fields = ["id", "article", "left", "right", "created_at"]

    def get_article(self, obj):
        return {
            "id": obj.article_id,
            "title": obj.article.original_title,
            "lead": obj.article.lead,
            "content": obj.article.content,
            "url": obj.article.url,
            "source": obj.article.source_id,
            "published_at_jalali": obj.article.published_at_jalali,
        }

    def _side(self, obj, variant):
        classification = obj.article.classifications.filter(variant=variant).first()
        evaluation = obj.article.evaluations.filter(variant=variant).first()
        summary = obj.article.summaries.filter(variant=variant).first()
        return {
            "category": classification.category if classification else None,
            "confidence": labelled(
                classification.confidence if classification else None, LEVEL_LABELS
            ),
            "classification_rationale": classification.rationale if classification else None,
            "scores": (
                {axis: labelled(getattr(evaluation, axis), LEVEL_LABELS) for axis in AXES}
                if evaluation else None
            ),
            "gold_trend": labelled(evaluation.gold_trend if evaluation else None, TREND_LABELS),
            "evaluation_rationale": evaluation.rationale if evaluation else None,
            "decision": (
                {"status": evaluation.decision.status, "reason": evaluation.decision.reason}
                if evaluation else None
            ),
            "one_line": summary.one_line if summary else None,
        }

    def get_left(self, obj):
        return self._side(obj, obj.variant_on("left"))

    def get_right(self, obj):
        return self._side(obj, obj.variant_on("right"))


class ABFeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = ABFeedback
        fields = ["id", "pair", "winner", "reasoning", "created_at"]
        read_only_fields = ["id", "created_at"]


# ------------------------------------------------------------------------------- market


class PriceSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceSnapshot
        fields = ["symbol", "price", "observed_at"]


class PredictionOutcomeSerializer(serializers.ModelSerializer):
    article_id = serializers.IntegerField(source="evaluation.article_id", read_only=True)
    gold_trend = serializers.CharField(source="evaluation.gold_trend", read_only=True)
    gold_price_impact = serializers.CharField(
        source="evaluation.gold_price_impact", read_only=True
    )

    class Meta:
        model = PredictionOutcome
        fields = [
            "id", "article_id", "symbol", "window_trading_days", "gold_trend",
            "gold_price_impact", "baseline_price", "realized_price", "realized_pct",
            "direction_correct", "computed_at",
        ]


class RunSerializer(serializers.ModelSerializer):
    class Meta:
        model = Run
        fields = [
            "run_id", "mode", "status", "started_at", "finished_at",
            "articles_fetched", "articles_processed", "cost_usd", "tokens_in", "tokens_out",
            "error",
        ]


