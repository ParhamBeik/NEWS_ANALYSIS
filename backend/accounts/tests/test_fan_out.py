"""Alert fan-out against real rows: dial, cap, quiet hours, tier-5 exemption, merges."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from accounts.models import Account, Alert, AlertState, Delivery, Device, Watch
from accounts.tasks import fan_out_event
from articles.models import EventWatchItem, NewsEvent, WatchItem
from core.events import attach_article, merge_events

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("alerts_on")]

# Fixed bands apply below 200 scored events: impact = 0.6 iran + 0.4 global.
TIER3 = {"iran_score": 50, "global_score": 50}  # impact 50 -> tier 3, global tier 3
TIER4 = {"iran_score": 75, "global_score": 50}  # impact 65 -> tier 4
TIER5 = {"iran_score": 100, "global_score": 75}  # impact 90 -> tier 5, global tier 4
BREAKING = {"iran_score": 0, "global_score": 100}  # global tier 5


@pytest.fixture
def alerts_on():
    with override_settings(NEWS_ALERTS_ENABLED=True):
        yield


@pytest.fixture
def item(db):
    return WatchItem.objects.create(slug="usd_irr", kind="asset", name_fa="دلار", name_en="Dollar")


def reader(name="+989120000001", *, dial="medium", watching=None, **fields):
    user = get_user_model().objects.create_user(username=f"tel:{name}")
    # A quiet window that never matches, unless a test sets one.
    fields.setdefault("quiet_start", time(0))
    fields.setdefault("quiet_end", time(0))
    Account.objects.create(user=user, phone=name, dial=dial, **fields)
    if watching:
        Watch.objects.create(user=user, item=watching)
    return user


def event_for(make_article, item=None, *, evidence="single", **scores):
    event = attach_article(make_article())
    NewsEvent.objects.filter(pk=event.pk).update(
        category="currency_gold", evidence_level=evidence, **scores
    )
    if item:
        EventWatchItem.objects.create(event=event, item=item)
    return NewsEvent.objects.get(pk=event.pk)


def test_watched_event_at_or_above_the_dial_alerts_and_records_deliveries(make_article, item):
    user = reader(watching=item)
    device = Device.objects.create(
        user=user, kind="fcm", token="t", last_seen=datetime.now(ZoneInfo("UTC"))
    )
    event = event_for(make_article, item, **TIER3)
    assert fan_out_event(event.id) == {"status": "done", "alerts": 1}
    alert = Alert.objects.get(user=user)
    assert (alert.kind, alert.tier, alert.held, alert.breaking) == ("new", 3, "", False)
    # No FCM keys in tests: the adapter no-ops, and the attempt is still recorded.
    delivery = Delivery.objects.get(alert=alert)
    assert (delivery.channel, delivery.device, delivery.status) == ("fcm", device, "disabled")


def test_below_the_dial_or_unwatched_does_not_alert(make_article, item):
    reader("+989120000001", dial="high", watching=item)
    reader("+989120000002", dial="low")
    event = event_for(make_article, item, **TIER3)
    assert fan_out_event(event.id)["alerts"] == 0


def test_global_tier_five_is_breaking_for_every_account(make_article):
    first, second = reader("+989120000001"), reader("+989120000002", dial="high")
    event = event_for(make_article, **BREAKING)
    assert fan_out_event(event.id)["alerts"] == 2
    assert set(Alert.objects.filter(breaking=True).values_list("user", flat=True)) == {
        first.id, second.id,
    }


def test_alerts_stay_off_until_enabled(make_article, item):
    reader(watching=item)
    event = event_for(make_article, item, **TIER3)
    with override_settings(NEWS_ALERTS_ENABLED=False):
        assert fan_out_event(event.id) == {"status": "disabled"}


def test_daily_cap_holds_the_sixth_push_but_not_tier_five(make_article, item):
    user = reader(watching=item)
    for _ in range(5):
        fan_out_event(event_for(make_article, item, **TIER3).id)
    assert Alert.objects.filter(user=user, held="").count() == 5
    fan_out_event(event_for(make_article, item, **TIER4).id)
    assert Alert.objects.latest("id").held == "cap"
    fan_out_event(event_for(make_article, item, **TIER5).id)
    assert Alert.objects.latest("id").held == ""


def test_quiet_hours_hold_the_push_but_tier_five_breaks_through(make_article, item):
    now = datetime.now(ZoneInfo("Asia/Tehran"))
    reader(watching=item, quiet_start=(now - timedelta(hours=1)).time(),
           quiet_end=(now + timedelta(hours=1)).time())
    fan_out_event(event_for(make_article, item, **TIER3).id)
    assert Alert.objects.latest("id").held == "quiet"
    fan_out_event(event_for(make_article, item, **TIER5).id)
    assert Alert.objects.latest("id").held == ""


def test_updates_only_on_evidence_flip_or_tier_rise(make_article, item):
    user = reader(watching=item)
    event = event_for(make_article, item, **TIER3)
    fan_out_event(event.id)
    fan_out_event(event.id)
    assert Alert.objects.filter(user=user).count() == 1
    NewsEvent.objects.filter(pk=event.pk).update(evidence_level="multi")
    fan_out_event(event.id)
    NewsEvent.objects.filter(pk=event.pk).update(**TIER4)
    fan_out_event(event.id)
    NewsEvent.objects.filter(pk=event.pk).update(**TIER3)
    fan_out_event(event.id)
    assert list(Alert.objects.filter(user=user).order_by("id").values_list("kind", "tier")) == [
        ("new", 3), ("update", 3), ("update", 4),
    ]


def test_a_merge_never_re_alerts(make_article, item):
    user = reader(watching=item)
    absorbed = event_for(make_article, item, **TIER3)
    fan_out_event(absorbed.id)
    target = event_for(make_article, item, **TIER3)
    merged = merge_events(target.id, absorbed.id)
    NewsEvent.objects.filter(pk=merged.pk).update(evidence_level="multi", **TIER4)
    assert fan_out_event(merged.id, merged=True)["alerts"] == 0
    alert = Alert.objects.get(user=user)
    assert alert.event_id == target.id  # the inbox row followed the merge
    state = AlertState.objects.get(user=user)
    assert (state.event_id, state.tier, state.evidence_level) == (target.id, 4, "multi")
    # Rebased: the next ordinary reassessment of the same state is silent too.
    assert fan_out_event(merged.id)["alerts"] == 0
