from django.contrib import admin

from .models import Account, Alert, Delivery, Device, Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ["slug", "name", "alerts", "depth", "exports"]


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "phone", "plan", "dial", "onboarded_at", "created_at"]
    search_fields = ["=phone", "user__username"]
    list_select_related = ["user", "plan"]


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "kind", "last_seen"]
    list_filter = ["kind"]
    exclude = ["token"]


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "event", "kind", "tier", "breaking", "held", "created_at"]
    list_filter = ["kind", "held", "breaking"]
    raw_id_fields = ["user", "event"]


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ["id", "alert", "channel", "status", "error", "created_at"]
    list_filter = ["channel", "status"]
    raw_id_fields = ["alert", "device"]
