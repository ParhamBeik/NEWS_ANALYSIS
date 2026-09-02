from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from articles.models import Article
from inference.models import Classification, Evaluation, NodeEvent, PromptVariant, Run, Summary
from review.models import ABFeedback, ABPair, ReviewCase, ReviewStatus

from .serializers import (
    ABFeedbackSerializer,
    ABPairSerializer,
    ArticleSerializer,
    PromptVariantSerializer,
    ReviewCaseSerializer,
    RunSerializer,
)


class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok"})


class ArticleViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ArticleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Article.objects.canonical().select_related("source").prefetch_related("image")
        if source := self.request.query_params.get("source"):
            queryset = queryset.filter(source_id=source)
        if category := self.request.query_params.get("category"):
            queryset = queryset.filter(classifications__category=category)
        if self.request.query_params.get("notify") == "true":
            queryset = queryset.filter(
                evaluations__confidence_occurrence__in=["زیاد", "خیلی زیاد"],
                evaluations__security_relevance__in=["زیاد", "خیلی زیاد"],
            )
        return queryset.distinct()


class RunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Run.objects.all()
    serializer_class = RunSerializer
    permission_classes = [IsAuthenticated]


class VariantViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PromptVariant.objects.all()
    serializer_class = PromptVariantSerializer
    permission_classes = [IsAuthenticated]


class ReviewViewSet(viewsets.ModelViewSet):
    serializer_class = ReviewCaseSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return ReviewCase.objects.select_related("article", "article__source").filter(
            status=ReviewStatus.PENDING
        )

    def perform_update(self, serializer):
        serializer.save(reviewer=self.request.user)


class ABPairViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ABPairSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ABPair.objects.select_related("article", "variant_a", "variant_b").prefetch_related(
            "feedback"
        )

    @action(detail=True, methods=["post"], url_path="feedback")
    def feedback(self, request, pk=None):
        pair = self.get_object()
        serializer = ABFeedbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ABFeedback.objects.update_or_create(
            pair=pair, user=request.user,
            defaults=serializer.validated_data,
        )
        return Response({"saved": True}, status=status.HTTP_200_OK)


class KPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        events = NodeEvent.objects.aggregate(
            total=Count("id"),
            success=Count("id", filter=Q(status="success")),
            failures=Count("id", filter=~Q(status__in=["success", "skipped"])),
        )
        return Response({
            "articles": Article.objects.canonical().count(),
            "classified": Classification.objects.count(),
            "evaluated": Evaluation.objects.count(),
            "summarized": Summary.objects.count(),
            "review_pending": ReviewCase.objects.filter(status=ReviewStatus.PENDING).count(),
            "ab_feedback": ABFeedback.objects.count(),
            "node_events": events,
        })
