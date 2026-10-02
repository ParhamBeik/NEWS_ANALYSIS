"""Reader accounts API: phone sign-in, profile, watchlist, devices, inbox, deletion.

Sign-in issues the same DRF token the web (httpOnly cookie) and the mobile app already
send as `Authorization: Token ...`. Staff username/password sign-in is untouched.
"""

from __future__ import annotations

import json
from datetime import time

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from accounts.models import Account, Alert, Device, Watch
from articles.models import NewsEvent, WatchItem
from core.otp import OTPError, normalize_phone, request_code, verify_code

from .public import AlertThrottle, ReaderView, valid_push_subscription

MAX_WATCH_ITEMS = 100
MIN_ONBOARDING_ITEMS = 3


class OTPRequestThrottle(AnonRateThrottle):
    scope = "otp_request"


class OTPVerifyThrottle(AnonRateThrottle):
    scope = "otp_verify"


def otp_refusal(error: OTPError) -> Response:
    code = {"invalid_phone": 400, "invalid_code": 400, "too_soon": 429, "too_many": 429}.get(
        error.code, 503
    )
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
    return Response({"error": error.code}, status=code, headers=headers)


def account_for(user) -> Account:
    account, _ = Account.objects.select_related("plan").get_or_create(user=user)
    return account


def watch_item_document(item: WatchItem) -> dict:
    return {"slug": item.slug, "kind": item.kind, "name_fa": item.name_fa, "name_en": item.name_en}


def watchlist(user) -> list[dict]:
    items = WatchItem.objects.filter(pk__in=Watch.objects.filter(user=user).values("item"))
    return [watch_item_document(item) for item in items.order_by("kind", "slug")]


def local_phone(phone: str | None) -> str | None:
    return "0" + phone.removeprefix("+98") if phone else None


def account_document(account: Account) -> dict:
    return {
        "phone": local_phone(account.phone),
        "email": account.email,
        "dial": account.dial,
        "quiet_start": account.quiet_start.strftime("%H:%M"),
        "quiet_end": account.quiet_end.strftime("%H:%M"),
        "email_digest": account.email_digest,
        "onboarded": account.onboarded_at is not None,
        "entitlements": account.entitlements(),
        "watchlist": watchlist(account.user),
        "unread": Alert.objects.filter(user=account.user, read_at__isnull=True).count(),
    }


# ---------------------------------------------------------------------------- sign-in


class OTPRequestView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [OTPRequestThrottle]

    def post(self, request):
        try:
            request_code(normalize_phone(request.data.get("phone")))
        except OTPError as error:
            return otp_refusal(error)
        return Response({"sent": True}, status=status.HTTP_202_ACCEPTED)


class OTPVerifyView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [OTPVerifyThrottle]

    def post(self, request):
        try:
            phone = normalize_phone(request.data.get("phone"))
            verify_code(phone, request.data.get("code"))
        except OTPError as error:
            return otp_refusal(error)
        account = Account.objects.select_related("user").filter(phone=phone).first()
        created = account is None
        if created:
            # "tel:" cannot be claimed through username signup (the validator rejects ":").
            try:
                with transaction.atomic():
                    # No password: create_user stores an unusable one.
                    user = get_user_model().objects.create_user(username=f"tel:{phone}")
                    account = Account.objects.create(user=user, phone=phone)
            except IntegrityError:
                account = Account.objects.select_related("user").get(phone=phone)
                created = False
        if not account.user.is_active:
            return Response({"error": "account_disabled"}, status=status.HTTP_403_FORBIDDEN)
        token, _ = Token.objects.get_or_create(user=account.user)
        return Response(
            {"token": token.key, "created": created, "onboarded": account.onboarded_at is not None},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------- profile


def parse_time(value, field: str) -> time:
    try:
        hour, minute = (int(part) for part in str(value).split(":"))
        return time(hour, minute)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field: "use HH:MM"}) from exc


class AccountView(APIView):
    def get(self, request):
        return Response(account_document(account_for(request.user)))

    def patch(self, request):
        account = account_for(request.user)
        data, fields = request.data, []
        if "dial" in data:
            if data["dial"] not in Account.Dial.values:
                raise ValidationError({"dial": f"choose one of {', '.join(Account.Dial.values)}"})
            account.dial = data["dial"]
            fields.append("dial")
        for name in ("quiet_start", "quiet_end"):
            if name in data:
                setattr(account, name, parse_time(data[name], name))
                fields.append(name)
        if "email" in data:
            email = str(data["email"] or "").strip()
            if email:
                try:
                    validate_email(email)
                except DjangoValidationError as exc:
                    raise ValidationError({"email": "enter a valid email"}) from exc
            account.email = email
            fields.append("email")
        if "email_digest" in data:
            account.email_digest = bool(data["email_digest"])
            fields.append("email_digest")
        if data.get("onboarded") and account.onboarded_at is None:
            if Watch.objects.filter(user=request.user).count() < MIN_ONBOARDING_ITEMS:
                raise ValidationError(
                    {"watchlist": f"pick at least {MIN_ONBOARDING_ITEMS} watch items"}
                )
            account.onboarded_at = timezone.now()
            fields.append("onboarded_at")
        if fields:
            account.save(update_fields=fields)
        return Response(account_document(account))

    def delete(self, request):
        """Delete the account now: user, token, watchlist, devices and alerts cascade."""
        if request.user.is_staff or request.user.is_superuser:
            raise ValidationError({"account": "staff accounts are removed by an administrator"})
        request.user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# -------------------------------------------------------------------------- watchlist


class PublicWatchItemsView(ReaderView):
    """The chips a reader can follow."""

    def get(self, request):
        items = WatchItem.objects.filter(enabled=True).order_by("kind", "name_en")
        return Response({"results": [watch_item_document(item) for item in items]})


def items_for(slugs) -> list[WatchItem]:
    if not isinstance(slugs, list) or not all(isinstance(slug, str) for slug in slugs):
        raise ValidationError({"slugs": "send a list of watch-item slugs"})
    items = list(WatchItem.objects.filter(slug__in=set(slugs), enabled=True))
    if len(items) != len(set(slugs)):
        known = {item.slug for item in items}
        raise ValidationError({"slugs": f"unknown: {', '.join(sorted(set(slugs) - known))}"})
    return items


class WatchlistView(APIView):
    def get(self, request):
        return Response({"results": watchlist(request.user)})

    def put(self, request):
        """Replace the whole watchlist (onboarding and the settings page)."""
        items = items_for(request.data.get("slugs"))
        if len(items) > MAX_WATCH_ITEMS:
            raise ValidationError({"slugs": f"at most {MAX_WATCH_ITEMS} items"})
        with transaction.atomic():
            Watch.objects.filter(user=request.user).exclude(item__in=items).delete()
            for item in items:
                Watch.objects.get_or_create(user=request.user, item=item)
        return Response({"results": watchlist(request.user)})

    def post(self, request):
        items = items_for([request.data.get("slug")])
        if Watch.objects.filter(user=request.user).count() >= MAX_WATCH_ITEMS:
            raise ValidationError({"slugs": f"at most {MAX_WATCH_ITEMS} items"})
        Watch.objects.get_or_create(user=request.user, item=items[0])
        return Response({"results": watchlist(request.user)}, status=status.HTTP_201_CREATED)


class WatchlistItemView(APIView):
    def delete(self, request, slug: str):
        deleted, _ = Watch.objects.filter(user=request.user, item__slug=slug).delete()
        if not deleted:
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------- devices


def device_token(kind, token) -> str:
    if kind not in Device.Kind.values:
        raise ValidationError({"kind": f"choose one of {', '.join(Device.Kind.values)}"})
    if kind == Device.Kind.WEBPUSH:
        if not valid_push_subscription(token):
            raise ValidationError({"token": "invalid browser push subscription"})
        keys = token["keys"]
        token = json.dumps(
            {
                "endpoint": token["endpoint"],
                "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]},
            },
            sort_keys=True,
        )
    if not isinstance(token, str) or not 1 <= len(token) <= 4096:
        raise ValidationError({"token": "invalid device token"})
    return token


class DeviceView(APIView):
    """Register or drop a push endpoint: the Expo app (fcm/pushe/najva) or the web PWA."""

    throttle_classes = [AlertThrottle]

    def post(self, request):
        kind = request.data.get("kind")
        token = device_token(kind, request.data.get("token"))
        # A token belongs to the device; whoever signed in on it last receives its pushes.
        device, created = Device.objects.update_or_create(
            kind=kind, token=token, defaults={"user": request.user, "last_seen": timezone.now()}
        )
        return Response(
            {"id": device.id, "kind": device.kind},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request):
        kind = request.data.get("kind")
        token = device_token(kind, request.data.get("token"))
        Device.objects.filter(user=request.user, kind=kind, token=token).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------------------ inbox


class InboxView(APIView):
    def get(self, request):
        rows = (
            Alert.objects.filter(user=request.user)
            .filter(event__in=NewsEvent.objects.visible())
            .select_related("event__primary_article")
            .order_by("-created_at", "-id")[:100]
        )
        return Response({
            "unread": Alert.objects.filter(user=request.user, read_at__isnull=True).count(),
            "results": [
                {
                    "id": row.id,
                    "kind": row.kind,
                    "tier": row.tier,
                    "breaking": row.breaking,
                    "held": row.held or None,
                    "evidence_level": row.evidence_level,
                    "created_at": row.created_at,
                    "read": row.read_at is not None,
                    "event": {
                        "id": row.event_id,
                        "title": row.event.title_fa or row.event.primary_article.original_title,
                        "title_en": row.event.title_en or None,
                        "category": row.event.category or None,
                    },
                }
                for row in rows
            ],
        })


class InboxReadView(APIView):
    def post(self, request):
        rows = Alert.objects.filter(user=request.user, read_at__isnull=True)
        if not request.data.get("all"):
            ids = request.data.get("ids")
            if not isinstance(ids, list) or not all(isinstance(value, int) for value in ids):
                raise ValidationError({"ids": "send a list of alert ids or all: true"})
            rows = rows.filter(pk__in=ids)
        return Response({"marked": rows.update(read_at=timezone.now())})
