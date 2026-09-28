from django.contrib import admin

from core.admin import EvidenceAdmin

from .models import CrawlAttempt, Source


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ["name", "display_name", "enabled", "strategy", "last_success_at"]
    search_fields = ["name", "display_name"]
    list_filter = ["enabled", "strategy"]
    readonly_fields = ["health_status", "last_success_at", "last_error", "created_at", "updated_at"]

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CrawlAttempt)
class CrawlAttemptAdmin(EvidenceAdmin):
    list_display = ["source", "started_at", "finished_at", "status", "new", "repeated", "failed"]
    list_filter = ["source", "status"]
    search_fields = ["task_id", "=source__name"]
    list_select_related = ["source"]
