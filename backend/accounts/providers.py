"""Outbound channels: SMS codes, push and email. Each one is off until its keys are set.

Nothing here logs a request URL or exception text: Kavenegar puts the API key in the path,
and a `requests` exception message repeats the URL.
"""

from __future__ import annotations

import base64
import json
import logging
import time

import requests
from django.conf import settings
from django.core.cache import cache

from core.errors import Permanent

logger = logging.getLogger(__name__)

KAVENEGAR_LOOKUP = "https://api.kavenegar.com/v1/{key}/verify/lookup.json"
FCM_SEND = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
TIMEOUT = 10


# ---------------------------------------------------------------------------------- SMS


def send_otp(phone: str, code: str) -> None:
    """Send a sign-in code through Kavenegar Verify Lookup.

    Without KAVENEGAR_API_KEY / KAVENEGAR_OTP_TEMPLATE: in DEBUG the code is printed to
    the console (local development); otherwise Permanent('sms_unavailable').
    """
    key, template = settings.KAVENEGAR_API_KEY, settings.KAVENEGAR_OTP_TEMPLATE
    if not (key and template):
        if settings.DEBUG:
            logger.warning("DEBUG sign-in code for %s: %s", phone, code)
            return
        raise Permanent("sms_unavailable")
    try:
        response = requests.post(
            KAVENEGAR_LOOKUP.format(key=key),
            data={"receptor": "0" + phone.removeprefix("+98"), "token": code,
                  "template": template},
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        logger.warning("kavenegar transport error")
        raise Permanent("sms_unavailable") from None
    if response.status_code != 200:
        logger.warning("kavenegar refused lookup: http %s", response.status_code)
        raise Permanent("sms_unavailable")


# --------------------------------------------------------------------------------- push


def send_push(device, payload: dict) -> tuple[str, str]:
    """(status, error) for one device; status is a Delivery.Status value."""
    sender = {"webpush": _webpush, "fcm": _fcm}.get(device.kind)
    if sender is None:
        # Pushe and Najva tokens are registered now; their senders are written once the
        # owner picks one and supplies its API key and contract.
        return "disabled", "no_adapter"
    return sender(device.token, payload)


def _webpush(token: str, payload: dict) -> tuple[str, str]:
    if not (settings.NEWS_VAPID_PRIVATE_KEY and settings.NEWS_VAPID_SUBJECT):
        return "disabled", "vapid_unset"
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info=json.loads(token),
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=settings.NEWS_VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.NEWS_VAPID_SUBJECT},
            ttl=3600,
        )
    except (ValueError, TypeError):
        return "expired", "bad_subscription"
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in {404, 410}:
            return "expired", f"push_http_{status}"
        return "failed", f"push_http_{status}" if status else "push_transport"
    return "sent", ""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _fcm_access_token(credentials: dict) -> str:
    """OAuth2 token from a service-account key (JWT bearer grant), cached ~50 minutes."""
    cached = cache.get("fcm:access_token")
    if cached:
        return cached
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    now = int(time.time())
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64(json.dumps({
        "iss": credentials["client_email"],
        "scope": "https://www.googleapis.com/auth/firebase.messaging",
        "aud": GOOGLE_TOKEN, "iat": now, "exp": now + 3600,
    }).encode())
    key = serialization.load_pem_private_key(credentials["private_key"].encode(), None)
    signature = key.sign(f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    response = requests.post(GOOGLE_TOKEN, timeout=TIMEOUT, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": f"{header}.{claims}.{_b64(signature)}",
    })
    response.raise_for_status()
    token = response.json()["access_token"]
    cache.set("fcm:access_token", token, 50 * 60)
    return token


def _fcm(token: str, payload: dict) -> tuple[str, str]:
    path = settings.FCM_CREDENTIALS_FILE
    if not (path and settings.FCM_PROJECT_ID):
        return "disabled", "fcm_unset"
    try:
        with open(path, encoding="utf-8") as handle:
            access = _fcm_access_token(json.load(handle))
        response = requests.post(
            FCM_SEND.format(project=settings.FCM_PROJECT_ID),
            headers={"Authorization": f"Bearer {access}"},
            json={"message": {
                "token": token,
                "notification": {"title": payload["title"], "body": payload["body"]},
                "data": {"url": payload["url"]},
            }},
            timeout=TIMEOUT,
        )
    except (OSError, ValueError, KeyError, requests.RequestException):
        return "failed", "fcm_transport"
    if response.status_code in {404, 400} and "UNREGISTERED" in response.text:
        return "expired", "fcm_unregistered"
    if response.status_code != 200:
        return "failed", f"fcm_http_{response.status_code}"
    return "sent", ""


# -------------------------------------------------------------------------------- email


def email_enabled() -> bool:
    return bool(settings.EMAIL_HOST)
