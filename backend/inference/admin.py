from django.contrib import admin

from core.admin import EvidenceAdmin

from .models import Classification, Evaluation, NodeEvent, Run, Summary


class ResultAdmin(EvidenceAdmin):
    list_display = ["id", "article_id", "model", "created_at"]
    search_fields = ["=article__id", "article__original_title"]
    list_filter = ["model"]


for model in (Classification, Evaluation, Summary):
    admin.site.register(model, ResultAdmin)


@admin.register(Run)
class RunAdmin(EvidenceAdmin):
    list_display = ["run_id", "started_at", "status", "articles_processed", "cost_usd"]
    list_filter = ["status"]
    search_fields = ["run_id"]


@admin.register(NodeEvent)
class NodeEventAdmin(EvidenceAdmin):
    list_display = ["id", "node", "status", "article_id", "created_at"]
    list_filter = ["node", "status"]
    search_fields = ["=article__id", "run__run_id"]
