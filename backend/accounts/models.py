"""Reader accounts: phone identity, plan, watchlist, devices and the alert inbox.

Privacy (docs/PRODUCT_MAP.md, Phase 5): store the phone, an optional email, the watchlist
and device tokens - nothing else about a person. OTP codes live only in the cache. Deleting
the Django user cascades through every row here.
"""

from __future__ import annotations

from datetime import time

from django.conf import settings
from django.db import models


class Plan(models.Model):
    """Entitlements. Every flag is granted on the free plan; paid plans come later."""

    FREE = "free"

    slug = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=64)
    alerts = models.BooleanField(default=True)
    depth = models.BooleanField(default=True)
    exports = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.slug

    @classmethod
    def free(cls) -> Plan:
        plan, _ = cls.objects.get_or_create(slug=cls.FREE, defaults={"name": "Free"})
        return plan


class Account(models.Model):
    """Reader profile beside the Django user. Staff users get one lazily, without a phone."""

    class Dial(models.TextChoices):
        # Lowest event tier that alerts: core.alerts.DIAL_MIN_TIER.
        LOW = "low", "Low (tier 2+)"
        MEDIUM = "medium", "Medium (tier 3+)"
        HIGH = "high", "High (tier 4+)"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account"
    )
    # Canonical +989xxxxxxxxx; one account per phone. NULL for staff accounts.
    phone = models.CharField(max_length=16, unique=True, null=True, blank=True)
    email = models.EmailField(blank=True)
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, null=True, blank=True)
    dial = models.CharField(max_length=8, choices=Dial, default=Dial.MEDIUM)
    # Tehran wall-clock times; a window may wrap midnight.
    quiet_start = models.TimeField(default=time(23, 0))
    quiet_end = models.TimeField(default=time(7, 0))
    email_digest = models.BooleanField(default=False)
    onboarded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"account {self.pk}"

    def entitlements(self) -> dict:
        plan = self.plan or Plan.free()
        return {
            "plan": plan.slug,
            "alerts": plan.alerts,
            "depth": plan.depth,
            "exports": plan.exports,
        }


class Watch(models.Model):
    """One watchlist entry. Watch items are the only unit: no free-text keywords."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="watches"
    )
    item = models.ForeignKey("articles.WatchItem", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "item"], name="one_watch_per_item")]

    def __str__(self) -> str:
        return f"user {self.user_id} watches {self.item_id}"


class Device(models.Model):
    """A push endpoint: an FCM/Pushe/Najva token from the app, or a web-push subscription."""

    class Kind(models.TextChoices):
        FCM = "fcm", "Firebase Cloud Messaging"
        PUSHE = "pushe", "Pushe"
        NAJVA = "najva", "Najva"
        WEBPUSH = "webpush", "Web push"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices"
    )
    kind = models.CharField(max_length=8, choices=Kind)
    # Web push stores the subscription JSON (endpoint + keys); the others an opaque token.
    token = models.TextField()
    last_seen = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "token"], name="one_device_per_token")
        ]

    def __str__(self) -> str:
        return f"{self.kind} device {self.pk}"


class AlertState(models.Model):
    """What a user was last told about an event: the re-alert ledger.

    An update alert fires only when the evidence level differs from `evidence_level` or the
    tier rises above `tier`. A merge rebases this row silently (core.alerts docstring).
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    event = models.ForeignKey("articles.NewsEvent", on_delete=models.CASCADE, related_name="+")
    tier = models.PositiveSmallIntegerField()
    evidence_level = models.CharField(max_length=16)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "event"], name="one_alert_state_per_event")
        ]

    def __str__(self) -> str:
        return f"user {self.user_id} last told tier {self.tier} on event {self.event_id}"


class Alert(models.Model):
    """One notification: always an inbox entry, and a push unless it was held."""

    class Kind(models.TextChoices):
        NEW = "new", "New event"
        UPDATE = "update", "Update"

    class Held(models.TextChoices):
        NONE = "", "Pushed"
        QUIET = "quiet", "Quiet hours"
        CAP = "cap", "Daily push cap"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alerts"
    )
    event = models.ForeignKey("articles.NewsEvent", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=8, choices=Kind)
    tier = models.PositiveSmallIntegerField()
    evidence_level = models.CharField(max_length=16)
    breaking = models.BooleanField(default=False)
    held = models.CharField(max_length=8, choices=Held, blank=True, default=Held.NONE)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self) -> str:
        return f"alert {self.pk}: event {self.event_id} to user {self.user_id}"


class Delivery(models.Model):
    """One attempt to deliver an alert on one channel."""

    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        DISABLED = "disabled", "Channel not configured"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Token expired"

    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name="deliveries")
    channel = models.CharField(max_length=8)
    device = models.ForeignKey(Device, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=8, choices=Status)
    error = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.channel} {self.status} for alert {self.alert_id}"
