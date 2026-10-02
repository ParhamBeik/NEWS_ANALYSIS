"""Alert fan-out and delivery. The rules are core.alerts; this module applies them.

Task names are persisted routing contracts (ARCHITECTURE.md): rename only with a
compatibility period.
"""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from articles.models import EventWatchItem, NewsEvent
from core import alerts, tiers

from .models import Account, Alert, AlertState, Delivery, Watch
from .providers import email_enabled, send_push


def tehran_midnight(now):
    local = now.astimezone(ZoneInfo(settings.TEHRAN_TZ))
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


@shared_task(name="accounts.fan_out_event")
def fan_out_event(event_id: int, merged: bool = False) -> dict:
    """Decide, per account, whether this assessed event alerts them, then queue pushes.

    `merged` is True when this assessment merged another event into this one: users
    already told about either event have their ledger rebased instead of re-alerted.
    """
    if not settings.NEWS_ALERTS_ENABLED:
        return {"status": "disabled"}
    event = NewsEvent.objects.visible().filter(pk=event_id).first()
    if (
        event is None
        or event.status == NewsEvent.Status.WITHDRAWN
        or event.category in {"", "other"}
        or event.iran_score is None
    ):
        return {"status": "not_alertable"}
    cuts = tiers.cutoffs()
    tier = tiers.tier(tiers.impact(event.iran_score, event.global_score), "impact", cuts)
    global_tier = tiers.tier(event.global_score, "global", cuts)
    breaking = global_tier == alerts.TOP_TIER
    items = EventWatchItem.objects.filter(event=event).values("item_id")
    watchers = set(Watch.objects.filter(item_id__in=items).values_list("user_id", flat=True))
    accounts = Account.objects.select_related("plan")
    if not breaking:
        accounts = accounts.filter(user_id__in=watchers)
    now = timezone.now()
    local_now = now.astimezone(ZoneInfo(settings.TEHRAN_TZ)).time()
    midnight = tehran_midnight(now)
    created = 0
    for account in accounts.iterator():
        why = alerts.reason(
            watched=account.user_id in watchers, tier=tier, global_tier=global_tier,
            dial=account.dial,
        )
        if not why or not account.entitlements()["alerts"]:
            continue
        with transaction.atomic():
            state = (
                AlertState.objects.select_for_update()
                .filter(user_id=account.user_id, event=event).first()
            )
            if merged and state is not None:
                state.tier, state.evidence_level = tier, event.evidence_level
                state.save(update_fields=["tier", "evidence_level", "updated_at"])
                continue
            previous = (state.tier, state.evidence_level) if state else None
            kind = alerts.change(previous, tier, event.evidence_level)
            if not kind:
                continue
            exempt = breaking or tier >= alerts.TOP_TIER
            pushed_today = (
                Alert.objects.filter(user_id=account.user_id, created_at__gte=midnight, held="")
                .filter(tier__lt=alerts.TOP_TIER, breaking=False)
                .count()
            )
            held = alerts.hold(
                exempt=exempt,
                quiet=alerts.in_quiet_hours(local_now, account.quiet_start, account.quiet_end),
                pushed_today=pushed_today,
            )
            if state is None:
                try:
                    with transaction.atomic():
                        AlertState.objects.create(
                            user_id=account.user_id, event=event, tier=tier,
                            evidence_level=event.evidence_level,
                        )
                except IntegrityError:
                    continue  # a concurrent fan-out for the same event got here first
            else:
                state.tier, state.evidence_level = tier, event.evidence_level
                state.save(update_fields=["tier", "evidence_level", "updated_at"])
            alert = Alert.objects.create(
                user_id=account.user_id, event=event, kind=kind, tier=tier,
                evidence_level=event.evidence_level, breaking=breaking, held=held,
            )
        created += 1
        if not held:
            deliver_alert.delay(alert.id)
    return {"status": "done", "alerts": created}


@shared_task(name="accounts.deliver_alert")
def deliver_alert(alert_id: int) -> dict:
    """Push one alert to each of the user's devices; one Delivery row per device."""
    alert = (
        Alert.objects.select_related("event__primary_article__source")
        .filter(pk=alert_id).first()
    )
    if alert is None:
        return {"status": "missing"}
    event = alert.event
    if event.hidden or event.primary_article.hidden:
        return {"status": "hidden"}
    prefix = "به‌روزرسانی: " if alert.kind == Alert.Kind.UPDATE else ""
    primary = event.primary_article
    # A facts_link_out source is never quoted, not even in a push body.
    lead = primary.lead if primary.source.license_mode != "facts_link_out" else ""
    payload = {
        "title": prefix + (event.title_fa or primary.original_title)[:120],
        "body": (event.brief_fa or lead)[:180],
        "url": f"/events/{event.id}",
    }
    done = set(alert.deliveries.filter(status="sent").values_list("device_id", flat=True))
    counts: dict[str, int] = {}
    for device in alert.user.devices.exclude(pk__in=done):
        status, error = send_push(device, payload)
        Delivery.objects.create(
            alert=alert, channel=device.kind, device=None if status == "expired" else device,
            status=status, error=error,
        )
        if status == "expired":
            device.delete()
        counts[status] = counts.get(status, 0) + 1
    return counts


@shared_task(name="accounts.send_email_digests")
def send_email_digests() -> dict:
    """Daily email of the last day's inbox, for accounts that opted in. Off without SMTP."""
    if not email_enabled():
        return {"status": "disabled"}
    since = timezone.now() - timedelta(days=1)
    sent = 0
    for account in Account.objects.filter(email_digest=True).exclude(email="").iterator():
        rows = list(
            Alert.objects.filter(user_id=account.user_id, created_at__gte=since)
            .exclude(deliveries__channel="email")
            .select_related("event__primary_article").order_by("-created_at")[:20]
        )
        if not rows:
            continue
        lines = [
            f"- {row.event.title_fa or row.event.primary_article.original_title}\n"
            f"  {settings.PUBLIC_SITE_URL}/events/{row.event_id}"
            for row in rows
        ]
        try:
            send_mail(
                "خلاصهٔ هشدارهای رادار خبر", "\n".join(lines), None, [account.email],
            )
            status, error = "sent", ""
            sent += 1
        except Exception as exc:  # one bad mailbox must not stop the batch
            status, error = "failed", type(exc).__name__[:64]
        Delivery.objects.bulk_create(
            Delivery(alert=row, channel="email", status=status, error=error) for row in rows
        )
    return {"status": "done", "sent": sent}
