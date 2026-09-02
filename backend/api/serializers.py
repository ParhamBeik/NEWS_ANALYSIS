from rest_framework import serializers

from articles.models import Article
from inference.models import Classification, Evaluation, PromptVariant, Run, Summary
from review.models import ABFeedback, ABPair, ReviewCase


class ArticleSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.display_name", read_only=True)
    image_url = serializers.SerializerMethodField()
    classification = serializers.SerializerMethodField()
    evaluation = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = [
            "id", "url", "source", "source_name", "original_outlet", "original_title",
            "lead", "content", "published_at", "published_at_jalali", "published_time",
            "native_category", "keywords", "extraction_tier", "quality_flag",
            "prefilter_reason", "image_url", "classification", "evaluation", "summary",
        ]

    def get_image_url(self, obj):
        image = getattr(obj, "image", None)
        if not image or not image.file:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(image.file.url) if request else image.file.url

    @staticmethod
    def _latest(queryset, obj):
        return queryset.filter(article=obj).order_by("-created_at", "-id").first()

    def get_classification(self, obj):
        row = self._latest(Classification.objects, obj)
        return None if row is None else {
            "category": row.category, "confidence": row.confidence,
            "provider": row.provider, "model": row.model, "rationale": row.rationale,
        }

    def get_evaluation(self, obj):
        row = self._latest(Evaluation.objects, obj)
        if row is None:
            return None
        return {
            "confidence_occurrence": row.confidence_occurrence,
            "gold_price_impact": row.gold_price_impact,
            "security_relevance": row.security_relevance,
            "gold_trend": row.gold_trend,
            "provider": row.provider, "model": row.model, "rationale": row.rationale,
        }

    def get_summary(self, obj):
        row = self._latest(Summary.objects, obj)
        return None if row is None else {
            "optimized_title": row.optimized_title, "one_line": row.one_line,
            "provider": row.provider, "model": row.model,
        }


class RunSerializer(serializers.ModelSerializer):
    class Meta:
        model = Run
        fields = "__all__"


class PromptVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromptVariant
        fields = ["id", "name", "description", "provider", "model", "memory_strategy",
                  "memory_k", "prompt_version", "is_active", "created_at"]
        read_only_fields = ["prompt_version", "created_at"]


class ReviewCaseSerializer(serializers.ModelSerializer):
    article = ArticleSerializer(read_only=True)

    class Meta:
        model = ReviewCase
        fields = "__all__"
        read_only_fields = ["reviewer", "reviewed_at", "created_at"]


class ABPairSerializer(serializers.ModelSerializer):
    left = serializers.SerializerMethodField()
    right = serializers.SerializerMethodField()
    feedback = serializers.SerializerMethodField()

    class Meta:
        model = ABPair
        fields = ["id", "article", "left", "right", "feedback", "created_at"]

    def _variant_payload(self, variant):
        return {
            "optimized_title": getattr(variant, "optimized_title", ""),
            "one_line": getattr(variant, "one_line", ""),
        }

    def _summary(self, pair, variant):
        return Summary.objects.filter(
            article=pair.article, variant=variant
        ).order_by("-created_at", "-id").first()

    def _side(self, pair, position):
        variant = pair.variant_on(position)
        summary = self._summary(pair, variant)
        return {
            "optimized_title": summary.optimized_title if summary else "",
            "one_line": summary.one_line if summary else "",
        }

    def get_left(self, obj):
        return self._side(obj, "left")

    def get_right(self, obj):
        return self._side(obj, "right")

    def get_feedback(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None
        row = obj.feedback.filter(user=request.user).first()
        return None if row is None else {"winner": row.winner, "reasoning": row.reasoning}


class ABFeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = ABFeedback
        fields = ["pair", "winner", "reasoning"]
