"""Phone sign-in codes. One account per phone; the code lives only in the cache.

Limits, all per phone (the API adds per-IP throttles on top, so one phone cannot be
hammered from many addresses and one address cannot spray many phones):
  - one code per RESEND_SECONDS, at most SENDS_PER_HOUR codes an hour;
  - a code lives CODE_SECONDS and allows VERIFY_ATTEMPTS guesses, then it is burned.
Only a salted hash of the code is stored, so a cache dump does not reveal live codes.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

from django.conf import settings
from django.core.cache import cache

from core.errors import Permanent

CODE_SECONDS = 120
RESEND_SECONDS = 60
SENDS_PER_HOUR = 5
VERIFY_ATTEMPTS = 5

_PERSIAN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_MOBILE = re.compile(r"9\d{9}")


class OTPError(Exception):
    """A refusal the caller can show: `code` is stable, the message is for logs."""

    def __init__(self, code: str, retry_after: int | None = None):
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


def normalize_phone(raw: str) -> str:
    """Canonical +989xxxxxxxxx for an Iranian mobile, or OTPError('invalid_phone').

    Accepts 0912..., 912..., +98912..., 0098912..., with Persian/Arabic digits, spaces
    and dashes - the forms people actually type.
    """
    digits = re.sub(r"[\s\-()]", "", str(raw or "")).translate(_PERSIAN)
    for prefix in ("+98", "0098", "98", "0"):
        if digits.startswith(prefix) and len(digits) - len(prefix) == 10:
            digits = digits[len(prefix):]
            break
    if not _MOBILE.fullmatch(digits):
        raise OTPError("invalid_phone")
    return f"+98{digits}"


def _digest(phone: str, code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"{phone}:{code}".encode(), "sha256").hexdigest()


def _key(kind: str, phone: str) -> str:
    return f"otp:{kind}:{hashlib.sha256(phone.encode()).hexdigest()[:32]}"


def request_code(phone: str) -> None:
    """Issue and send a code for an already-normalised phone."""
    from accounts.providers import send_otp

    if not cache.add(_key("cooldown", phone), 1, RESEND_SECONDS):
        raise OTPError("too_soon", RESEND_SECONDS)
    hourly = _key("hourly", phone)
    cache.add(hourly, 0, 3600)
    if cache.incr(hourly) > SENDS_PER_HOUR:
        raise OTPError("too_many", 3600)
    code = f"{secrets.randbelow(10**6):06d}"
    cache.set(
        _key("code", phone),
        {"hash": _digest(phone, code), "attempts": 0, "expires": time.time() + CODE_SECONDS},
        CODE_SECONDS,
    )
    try:
        send_otp(phone, code)
    except Permanent as exc:
        cache.delete(_key("code", phone))
        cache.delete(_key("cooldown", phone))
        raise OTPError(str(exc) or "sms_unavailable") from exc


def verify_code(phone: str, code: str) -> None:
    """Return on a match (and burn the code); OTPError('invalid_code') otherwise."""
    key = _key("code", phone)
    stored = cache.get(key)
    if not stored:
        raise OTPError("invalid_code")
    code = str(code or "").strip().translate(_PERSIAN)
    if hmac.compare_digest(stored["hash"], _digest(phone, code)):
        cache.delete(key)
        return
    stored["attempts"] += 1
    remaining = int(stored["expires"] - time.time())
    if stored["attempts"] >= VERIFY_ATTEMPTS or remaining <= 0:
        cache.delete(key)
    else:
        # The original expiry: a wrong guess must never extend a code's life.
        cache.set(key, stored, remaining)
    raise OTPError("invalid_code")
