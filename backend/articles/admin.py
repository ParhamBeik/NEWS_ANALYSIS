from django.contrib import admin

from core.admin import EvidenceAdmin

from .models import Article, EventReview, NewsEvent


@admin.register(Article)
class ArticleAdmin(EvidenceAdmin):
    list_display = ["id", "original_title", "source", "created_at", "extraction_tier"]
    list_filter = ["source", "extraction_tier", "url_status"]
    search_fields = ["=id", "original_title", "url"]
    list_select_related = ["source", "duplicate_of"]
    ordering = ["-created_at", "-id"]


@admin.register(NewsEvent)
class NewsEventAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "primary_article",
        "event_time",
        "status",
        "category",
        "iran_score",
        "global_score",
    ]
    list_filter = ["status", "category"]
    search_fields = ["=id", "primary_article__original_title"]
    readonly_fields = [
        "primary_article",
        "event_time",
        "first_seen_at",
        "status",
        "category",
        "iran_score",
        "global_score",
        "assessment_confidence",
        "title_fa",
        "brief_fa",
        "brief_en",
    ]


@admin.register(EventReview)
class EventReviewAdmin(admin.ModelAdmin):
    list_display = ["id", "event", "reason", "status", "created_at", "reviewed_at"]
    list_filter = ["status", "reason"]
    search_fields = ["=id", "event__primary_article__original_title"]
    readonly_fields = ["event", "reason", "created_at", "reviewer", "reviewed_at"]

    def save_model(self, request, obj, form, change):
        if obj.status == EventReview.Status.REVIEWED and not obj.reviewed_at:
            from django.utils import timezone

            obj.reviewer = request.user
            obj.reviewed_at = timezone.now()
        super().save_model(request, obj, form, change)
