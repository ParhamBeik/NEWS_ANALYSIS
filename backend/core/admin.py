from django.contrib import admin


class EvidenceAdmin(admin.ModelAdmin):
    """Generated evidence is inspectable, never edited or deleted through admin."""

    list_per_page = 50
    show_full_result_count = False
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.site_header = "News Intelligence"
admin.site.site_title = "News administration"
admin.site.site_url = "/"
