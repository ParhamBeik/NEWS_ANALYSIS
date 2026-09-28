from django.contrib import admin

from core.admin import EvidenceAdmin

from .models import ReviewCase


@admin.register(ReviewCase)
class ReviewCaseAdmin(EvidenceAdmin):
    list_display = ["id", "article_id", "status"]
    list_filter = ["status"]
    search_fields = ["=article__id", "article__original_title"]
