"""Phone sign-in throttling and the account API (watchlist, devices, inbox, deletion)."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import Account, Alert, Device, Watch
from api.accounts import OTPRequestThrottle
from articles.models import WatchItem
from core import otp
from core.events import attach_article

pytestmark = pytest.mark.django_db

PHONE = "0912 123 4567"
CANONICAL = "+989121234567"


@pytest.fixture
def sms():
    """Capture the codes instead of calling Kavenegar."""
    sent = []
    with patch("accounts.providers.send_otp", lambda phone, code: sent.append((phone, code))):
        yield sent


def sign_in(api, sms, phone=PHONE):
    assert api.post("/api/auth/otp/request/", {"phone": phone}).status_code == 202
    return api.post("/api/auth/otp/verify/", {"phone": phone, "code": sms[-1][1]})


@pytest.fixture
def items(db):
    return [
        WatchItem.objects.create(slug=slug, kind="asset", name_fa=slug, name_en=slug)
        for slug in ("usd_irr", "gold_18k", "oil_brent", "bitcoin")
    ]


@pytest.fixture
def member(db):
    user = get_user_model().objects.create_user(username="tel:+989120000009")
    Account.objects.create(user=user, phone="+989120000009")
    api = APIClient()
    api.force_authenticate(user)
    return api, user


# ---------------------------------------------------------------------------- sign-in


def test_phone_forms_normalise_to_one_identity():
    for raw in ("09121234567", "+98 912 123 4567", "00989121234567", "9121234567",
                "۰۹۱۲۱۲۳۴۵۶۷"):
        assert otp.normalize_phone(raw) == CANONICAL
    with pytest.raises(otp.OTPError):
        otp.normalize_phone("02112345678")


def test_sign_in_creates_one_account_per_phone_and_issues_a_token(sms):
    api = APIClient()
    first = sign_in(api, sms)
    assert first.status_code == 201 and first.data["created"] and not first.data["onboarded"]
    assert sms[-1][0] == CANONICAL
    cache.clear()  # past the resend cooldown
    again = sign_in(api, sms, phone="+989121234567")
    assert again.status_code == 200 and not again.data["created"]
    assert again.data["token"] == first.data["token"]
    assert Account.objects.filter(phone=CANONICAL).count() == 1
    authed = APIClient(HTTP_AUTHORIZATION=f"Token {first.data['token']}")
    assert authed.get("/api/account/").data["phone"] == "09121234567"
    assert authed.get("/api/auth/me/").data["display_name"] == "09121234567"


def test_resend_cooldown_and_hourly_cap_per_phone(sms):
    api = APIClient()
    assert api.post("/api/auth/otp/request/", {"phone": PHONE}).status_code == 202
    soon = api.post("/api/auth/otp/request/", {"phone": PHONE})
    assert soon.status_code == 429 and soon.data["error"] == "too_soon"
    assert soon["Retry-After"] == "60"
    for _ in range(otp.SENDS_PER_HOUR - 1):
        cache.delete(otp._key("cooldown", CANONICAL))
        assert api.post("/api/auth/otp/request/", {"phone": PHONE}).status_code == 202
    cache.delete(otp._key("cooldown", CANONICAL))
    capped = api.post("/api/auth/otp/request/", {"phone": PHONE})
    assert capped.status_code == 429 and capped.data["error"] == "too_many"
    # Another phone is unaffected by this phone's limit.
    assert api.post("/api/auth/otp/request/", {"phone": "09350000000"}).status_code == 202


def test_requests_are_throttled_per_address_across_phones(sms, monkeypatch):
    monkeypatch.setattr(
        OTPRequestThrottle, "THROTTLE_RATES",
        {**OTPRequestThrottle.THROTTLE_RATES, "otp_request": "3/hour"},
    )
    api = APIClient()
    codes = [api.post("/api/auth/otp/request/", {"phone": f"0912000000{n}"}).status_code
             for n in range(4)]
    assert codes == [202, 202, 202, 429]


def test_wrong_guesses_burn_the_code(sms):
    api = APIClient()
    api.post("/api/auth/otp/request/", {"phone": PHONE})
    code = sms[-1][1]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(otp.VERIFY_ATTEMPTS):
        response = api.post("/api/auth/otp/verify/", {"phone": PHONE, "code": wrong})
        assert response.status_code == 400 and response.data["error"] == "invalid_code"
    burned = api.post("/api/auth/otp/verify/", {"phone": PHONE, "code": code})
    assert burned.status_code == 400
    assert not Account.objects.exists()


def test_without_kavenegar_keys_sign_in_says_sms_unavailable():
    response = APIClient().post("/api/auth/otp/request/", {"phone": PHONE})
    assert response.status_code == 503 and response.data["error"] == "sms_unavailable"
    # The failed send does not leave the phone in its cooldown.
    with override_settings(DEBUG=True):
        assert APIClient().post("/api/auth/otp/request/", {"phone": PHONE}).status_code == 202


def test_staff_password_sign_in_still_works(user):
    response = APIClient().post(
        "/api/auth/token/", {"username": "analyst", "password": "test-pass"}
    )
    assert response.status_code == 200 and response.data["token"]


# ---------------------------------------------------------------------------- watchlist


def test_watch_items_are_public_chips(items):
    response = APIClient().get("/api/public/watch-items/")
    assert response.status_code == 200
    assert {row["slug"] for row in response.data["results"]} == {item.slug for item in items}


def test_watchlist_crud_and_onboarding_needs_three_items(member, items):
    api, user = member
    assert api.put("/api/account/watchlist/", {"slugs": ["usd_irr", "nope"]},
                   format="json").status_code == 400
    put = api.put("/api/account/watchlist/", {"slugs": ["usd_irr", "gold_18k"]}, format="json")
    assert [row["slug"] for row in put.data["results"]] == ["gold_18k", "usd_irr"]
    refused = api.patch("/api/account/", {"onboarded": True, "dial": "high"}, format="json")
    assert refused.status_code == 400
    assert api.post("/api/account/watchlist/", {"slug": "bitcoin"}).status_code == 201
    done = api.patch("/api/account/", {"onboarded": True, "dial": "high"}, format="json")
    assert done.status_code == 200 and done.data["onboarded"] and done.data["dial"] == "high"
    assert api.delete("/api/account/watchlist/bitcoin/").status_code == 204
    assert api.delete("/api/account/watchlist/bitcoin/").status_code == 404
    assert set(Watch.objects.filter(user=user).values_list("item__slug", flat=True)) == {
        "usd_irr", "gold_18k",
    }
    replaced = api.put("/api/account/watchlist/", {"slugs": ["oil_brent"]}, format="json")
    assert [row["slug"] for row in replaced.data["results"]] == ["oil_brent"]


def test_settings_validate_dial_quiet_hours_and_email(member):
    api, _ = member
    assert api.patch("/api/account/", {"dial": "max"}, format="json").status_code == 400
    assert api.patch("/api/account/", {"quiet_start": "25:00"}, format="json").status_code == 400
    assert api.patch("/api/account/", {"email": "nope"}, format="json").status_code == 400
    saved = api.patch("/api/account/", {"quiet_start": "22:30", "quiet_end": "06:00",
                                        "email": "a@example.com", "email_digest": True},
                      format="json").data
    assert (saved["quiet_start"], saved["quiet_end"], saved["email_digest"]) == (
        "22:30", "06:00", True,
    )
    assert saved["entitlements"] == {"plan": "free", "alerts": True, "depth": True,
                                     "exports": True}


def test_account_endpoints_need_a_sign_in():
    api = APIClient()
    for path in ("/api/account/", "/api/account/watchlist/", "/api/account/inbox/"):
        assert api.get(path).status_code in {401, 403}


# ----------------------------------------------------------------- devices and inbox


def test_device_registration_moves_a_token_to_the_latest_user(member, user):
    api, owner = member
    assert api.post("/api/account/devices/", {"kind": "fcm", "token": "abc"}).status_code == 201
    assert api.post("/api/account/devices/", {"kind": "sms", "token": "abc"}).status_code == 400
    other = APIClient()
    other.force_authenticate(user)
    assert other.post("/api/account/devices/", {"kind": "fcm", "token": "abc"}).status_code == 200
    assert Device.objects.get().user == user
    web = {"endpoint": "https://fcm.googleapis.com/fcm/send/x", "keys": {
        "p256dh": "p" * 40, "auth": "a" * 24}}
    assert api.post("/api/account/devices/", {"kind": "webpush", "token": web},
                    format="json").status_code == 201
    assert api.delete("/api/account/devices/", {"kind": "webpush", "token": web},
                      format="json").status_code == 204
    assert not Device.objects.filter(user=owner).exists()


def test_inbox_lists_and_marks_alerts_read(member, make_article):
    api, user = member
    event = attach_article(make_article())
    first, second = (
        Alert.objects.create(user=user, event=event, kind=kind, tier=3, evidence_level="single")
        for kind in ("new", "update")
    )
    inbox = api.get("/api/account/inbox/").data
    assert inbox["unread"] == 2 and [row["id"] for row in inbox["results"]] == [second.id, first.id]
    assert api.post("/api/account/inbox/read/", {"ids": [first.id]}, format="json").data == {
        "marked": 1,
    }
    assert api.post("/api/account/inbox/read/", {"all": True}, format="json").data == {"marked": 1}
    assert api.get("/api/account/inbox/").data["unread"] == 0


def test_account_deletion_wipes_everything_but_refuses_staff(member, items, make_article):
    api, user = member
    Watch.objects.create(user=user, item=items[0])
    Device.objects.create(user=user, kind="fcm", token="t", last_seen="2026-10-02T00:00Z")
    Alert.objects.create(user=user, event=attach_article(make_article()), kind="new", tier=3,
                         evidence_level="single")
    Token.objects.create(user=user)
    assert api.delete("/api/account/").status_code == 204
    assert not get_user_model().objects.filter(pk=user.pk).exists()
    for model in (Account, Watch, Device, Alert, Token):
        assert not model.objects.exists()
    staff = get_user_model().objects.create_user(username="ops", is_staff=True)
    api.force_authenticate(staff)
    assert api.delete("/api/account/").status_code == 400
