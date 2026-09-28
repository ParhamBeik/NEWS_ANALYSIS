from django.contrib import admin

from core.admin import EvidenceAdmin

from .models import Article


@admin.register(Article)
class ArticleAdmin(EvidenceAdmin):
    list_display = ["id", "original_title", "source", "created_at", "extraction_tier"]
    list_filter = ["source", "extraction_tier", "url_status"]
    search_fields = ["=id", "original_title", "url"]
    list_select_related = ["source", "duplicate_of"]
    ordering = ["-created_at", "-id"]
