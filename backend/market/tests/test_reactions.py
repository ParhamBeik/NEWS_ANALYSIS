"""Event-level back-test: reaction windows, trading days, z-scores, and the absent feed."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from articles.models import EventAssessment, NewsEvent
from market import reactions
from market.models import EventReaction, nth_trading_day
from market.tasks import compute_event_reactions

TEHRAN = ZoneInfo("Asia/Tehran")


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def hourly(start: datetime, hours: int, price=lambda i: 100 + i) -> list:
    return [(start + timedelta(hours=i), Decimal(price(i))) for i in range(hours)]


class TestWindows:
    EVENT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    NOW = EVENT + timedelta(days=5)

    def test_two_hours_either_side(self):
        points = hourly(self.EVENT - timedelta(hours=6), 12)  # 06:00 .. 17:00, price 100+i
        before, after = reactions.window_prices(points, self.EVENT, "2h", self.NOW)
        assert before[0] == self.EVENT - timedelta(hours=2) and before[1] == 104
        assert after[0] == self.EVENT + timedelta(hours=2) and after[1] == 108

    def test_one_day_uses_the_last_price_before_the_event_as_baseline(self):
        points = hourly(self.EVENT - timedelta(hours=3), 30)
        before, after = reactions.window_prices(points, self.EVENT, "1d", self.NOW)
        assert before[0] == self.EVENT
        assert after[0] == self.EVENT + timedelta(days=1)

    def test_a_window_the_market_has_not_answered_is_not_scored(self):
        points = hourly(self.EVENT - timedelta(hours=3), 30)
        assert reactions.window_prices(points, self.EVENT, "1d", self.EVENT + timedelta(hours=5)) \
            is None

    def test_a_stale_quote_after_the_event_is_not_a_reaction(self):
        points = [(self.EVENT - timedelta(hours=1), Decimal(100))]
        assert reactions.window_prices(points, self.EVENT, "1d", self.NOW) is None

    def test_a_baseline_far_from_the_window_edge_is_rejected(self):
        points = [(self.EVENT - timedelta(hours=8), Decimal(100)),
                  (self.EVENT + timedelta(hours=1), Decimal(110))]
        assert reactions.window_prices(points, self.EVENT, "2h", self.NOW) is None


class TestTradingDays:
    """Iranian markets: Thursday evening news, Friday closed, Saturday is day one."""

    THURSDAY = datetime(2026, 9, 24, 18, 0, tzinfo=TEHRAN)  # 2026-09-24 is a Thursday

    def daily(self):
        days = [datetime(2026, 9, d, 12, 30, tzinfo=TEHRAN) for d in (23, 24, 26, 27, 28)]
        return [(day, Decimal(1000 + 10 * i)) for i, day in enumerate(days)]

    def test_friday_is_skipped(self):
        stamps = [day for day, _ in self.daily()]
        assert nth_trading_day(stamps, self.THURSDAY, 1).day == 26
        assert nth_trading_day(stamps, self.THURSDAY, 3).day == 28
        assert nth_trading_day(stamps, self.THURSDAY, 4) is None

    def test_trading_day_windows(self):
        now = datetime(2026, 10, 1, tzinfo=TEHRAN)
        before, after = reactions.window_prices(self.daily(), self.THURSDAY, "1td", now)
        assert before[0].day == 24 and after[0].day == 26
        _, after = reactions.window_prices(self.daily(), self.THURSDAY, "3td", now)
        assert after[0].day == 28

    def test_iranian_assets_get_trading_day_windows(self):
        assert reactions.windows_for({"key": "tedpix"}) == ("1td", "3td")
        assert reactions.windows_for({"key": "x", "currency": "IRR"}) == ("1td", "3td")
        assert reactions.windows_for({"key": "brent", "currency": "USD"}) == ("2h", "1d")


class TestZScore:
    EVENT = datetime(2026, 9, 30, tzinfo=UTC)

    def series(self, days):
        # Alternating +1% / -1%-ish moves: the population sd of the moves is ~1%.
        prices, price = [], Decimal(100)
        for i in range(days):
            prices.append((self.EVENT - timedelta(days=days - i), price))
            price = price * (Decimal("1.01") if i % 2 == 0 else Decimal("100") / Decimal("101"))
        return prices

    def test_move_measured_in_trailing_daily_spreads(self):
        z = reactions.abs_z(-2.0, self.series(25), self.EVENT)
        assert z == pytest.approx(2.0, rel=0.02)

    def test_too_short_a_history_has_no_z(self):
        assert reactions.abs_z(2.0, self.series(5), self.EVENT) is None

    def test_a_flat_history_has_no_z(self):
        flat = [(self.EVENT - timedelta(days=i), Decimal(5)) for i in range(20, 0, -1)]
        assert reactions.abs_z(2.0, flat, self.EVENT) is None


def test_relevance_maps_old_asset_keys_and_watch_items():
    rows = {"brent": {}, "usd_irr": {}, "tedpix": {}, "btc_usd": {}}
    keys = reactions.relevant_keys({"oil": 75, "fx": 25, "bitcoin": 50}, ["tse_index"], rows)
    assert keys == {"brent", "btc_usd", "tedpix"}


# ------------------------------------------------------------------------------ sweep


def _event(make_article, when, iran=90, asset_scores=None):
    event = NewsEvent.objects.create(
        primary_article=make_article(published_at=when), event_time=when, first_seen_at=when,
        category="energy_commodities", iran_score=iran, global_score=iran,
    )
    EventAssessment.objects.create(
        event=event, model="jev", evidence_hash="h", category="energy_commodities",
        iran_score=iran, global_score=iran, asset_scores=asset_scores or {"oil": 75},
        confidence=0.9,
    )
    return event


@pytest.mark.django_db
@override_settings(PORTFOLIO_MARKET_BASE_URL="", PORTFOLIO_MARKET_SERVICE_KEY="")
def test_unavailable_portfolio_is_a_counted_skip_not_a_failure(make_article):
    from django.utils import timezone

    _event(make_article, timezone.now() - timedelta(days=2))
    assert compute_event_reactions() == {"status": "unavailable", "reason": "not_configured"}
    compute_event_reactions()
    assert EventReaction.objects.count() == 0
    status = reactions.calibration()
    assert status["unavailable_runs"] == 2 and status["configured"] is False
    assert status["last_run"]["reason"] == "not_configured"


@pytest.mark.django_db
def test_sweep_stores_global_windows_once_and_skips_low_tiers(make_article):
    from django.utils import timezone

    now = timezone.now().replace(minute=0, second=0, microsecond=0)
    event_time = now - timedelta(days=2)
    important = _event(make_article, event_time)
    _event(make_article, event_time, iran=10)  # tier 1: not back-tested
    catalog = {"available": True, "results": [
        {"key": "brent", "currency": "USD", "asset_class": "oil"},
        {"key": "tedpix", "currency": "IRR"},
    ]}
    start = event_time - timedelta(days=40)
    points = [{"observed_at": (start + timedelta(hours=i)).isoformat(),
               "price": str(100 + (i % 3))} for i in range(int((now - start).total_seconds()
                                                               // 3600))]

    def series(key, **kwargs):
        return {"available": True, "points": points}

    with patch.object(reactions.portfolio, "catalog", return_value=catalog), \
            patch.object(reactions.portfolio, "series", side_effect=series) as fetch:
        first = reactions.compute(now=now)
        second = reactions.compute(now=now)
    assert first["stored"] == 2 and second["stored"] == 0
    rows = EventReaction.objects.filter(event=important)
    assert {row.window for row in rows} == {"2h", "1d"}
    assert {row.asset_key for row in rows} == {"brent"}
    assert all(row.tier >= reactions.MIN_TIER and row.asset_class == "oil" for row in rows)
    assert all(row.abs_z is not None for row in rows)
    assert fetch.call_count == 2  # one daily and one hourly read per asset, not per event


@pytest.mark.django_db
def test_calibration_per_tier_and_asset_class(make_article):
    from django.utils import timezone

    event = _event(make_article, timezone.now() - timedelta(days=3))
    for window, tier, z in (("1d", 5, 2.0), ("2h", 5, 0.5), ("1td", 3, None)):
        EventReaction.objects.create(
            event=event, asset_key=f"k{window}", asset_class="oil", window=window, tier=tier,
            price_before=1, price_after=1, pct_change=0, abs_z=z,
        )
    data = reactions.calibration()
    by_tier = {row["key"]: row for row in data["by_tier"]}
    assert by_tier[5] == {"key": 5, "reactions": 2, "scored": 2, "mean_abs_z": 1.25,
                          "hit_rate": 0.5}
    assert by_tier[3]["hit_rate"] is None and by_tier[3]["reactions"] == 1
    assert data["by_asset_class"][0]["reactions"] == 3


@pytest.mark.django_db
def test_calibration_endpoint_is_staff_only():
    client = APIClient()
    reader = get_user_model().objects.create_user("reader", password="x")
    client.force_authenticate(reader)
    assert client.get("/api/ops/calibration/").status_code == 403
    staff = get_user_model().objects.create_user("staff", password="x", is_staff=True)
    client.force_authenticate(staff)
    response = client.get("/api/ops/calibration/")
    assert response.status_code == 200 and response.data["by_tier"] == []
