"""The gold back-test - ground truth that needs no human labelling.

Which is exactly why it has to be hard to flatter. Each test here corresponds to a way the
number could look better than the model deserves.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core.vocabulary import GoldTrend
from market.models import PredictionOutcome, PriceSnapshot, Symbol
from market.tasks import DIRECTION_DEADBAND_PCT, backtest_predictions
from market.tgju import parse_price, parse_timestamp

pytestmark = pytest.mark.django_db

GOLD = Symbol.GOLD_18K


def _at_ten():
    """A publication time pinned to mid-morning UTC.

    `timezone.now() + timedelta(hours=1)` is not reliably the same calendar day, so a test
    that depends on "still day zero" would pass all day and fail for the hour before
    midnight UTC. Pinning the hour removes the clock from the test.
    """
    return timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)


@pytest.fixture
def price():
    def _price(value, when):
        return PriceSnapshot.objects.create(symbol=GOLD, price=Decimal(value), observed_at=when)

    return _price


@pytest.fixture
def evaluation(make_article, variant):
    from inference.models import Evaluation

    def _make(published_at, trend=GoldTrend.UP, impact="زیاد"):
        article = make_article(published_at=published_at)
        return Evaluation.objects.create(
            article=article,
            variant=variant,
            prompt_version=variant.prompt_version,
            provider="gapgpt",
            model="m",
            confidence_occurrence="زیاد",
            gold_price_impact=impact,
            gold_trend=trend,
        )

    return _make


class TestBaseline:
    def test_baseline_is_the_last_price_before_publication(self, price, evaluation):
        """Using the first price AFTER publication would fold the very move being
        predicted into the baseline and report near-zero error for everything."""
        now = timezone.now()
        price(100, now - timedelta(hours=2))
        published = now - timedelta(hours=1)
        price(150, now)  # after publication - must NOT become the baseline
        price(160, now + timedelta(days=1))

        backtest_predictions(windows=(1,))
        # No evaluation yet, so nothing scored; create one and re-run.
        evaluation(published)
        backtest_predictions(windows=(1,))
        outcome = PredictionOutcome.objects.first()
        assert outcome is not None
        assert outcome.baseline_price == Decimal("100.0000")


class TestTradingDays:
    def test_a_closed_market_does_not_count_as_a_day(self, price, evaluation):
        """The Iranian gold market closes on Fridays and holidays. Counting calendar days
        would score a Thursday-evening prediction against a frozen price and call it 'no
        movement' - inflating apparent calibration on exactly the quiet days."""
        now = timezone.now()
        price(100, now - timedelta(hours=1))
        published = now
        # Market is closed for two days: no observations at all.
        price(120, now + timedelta(days=3))

        evaluation(published)
        backtest_predictions(windows=(1,))
        outcome = PredictionOutcome.objects.first()
        assert outcome is not None, "the first TRADING day is day 3, and it is scorable"
        assert outcome.realized_price == Decimal("120.0000")

    def test_not_enough_trading_days_yet_is_skipped_not_scored(self, price, evaluation):
        now = timezone.now()
        price(100, now - timedelta(hours=1))
        evaluation(now)
        result = backtest_predictions(windows=(5,))
        assert result["scored"] == 0
        assert PredictionOutcome.objects.count() == 0

    def test_the_publication_day_is_day_zero(self, price, evaluation):
        """A one-day window must not resolve to the next poll.

        Counting the publication day itself as day 1 meant an article published at 10:00
        was scored against the 10:15 observation - fifteen minutes of movement reported as
        a one-day return - and every window came out shorter than it claimed.
        """
        published = _at_ten()
        price(100, published - timedelta(hours=2))
        evaluation(published)
        price(150, published + timedelta(hours=1))  # still day zero
        price(200, published + timedelta(days=1))  # the first trading day AFTER

        backtest_predictions(windows=(1,))
        outcome = PredictionOutcome.objects.get(window_trading_days=1)
        assert outcome.realized_price == Decimal("200.0000")

    def test_multiple_observations_in_one_day_count_once(self, price, evaluation):
        """A day is a day however often the poller ran: day 1 is the FIRST observation of
        the first trading day after publication, not the fifteenth of that morning."""
        published = _at_ten()
        price(100, published - timedelta(hours=2))
        evaluation(published)
        for hour in (0, 1, 2):
            price(150 + hour, published + timedelta(days=1, hours=hour))
        price(200, published + timedelta(days=2))

        backtest_predictions(windows=(1, 2))
        assert PredictionOutcome.objects.get(
            window_trading_days=1
        ).realized_price == Decimal("150.0000")
        assert PredictionOutcome.objects.get(
            window_trading_days=2
        ).realized_price == Decimal("200.0000")

    def test_publication_across_utc_midnight_respects_tehran_calendar_day(
        self, price, evaluation
    ):
        """Articles published early morning Tehran time (e.g. 01:00 Tehran = 21:30 UTC
        previous day) share the same Tehran market calendar day as the 11:00 morning trade.
        The back-test must not treat the morning trade as trading day 1."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tehran = ZoneInfo("Asia/Tehran")
        pub = datetime(2026, 9, 3, 1, 0, tzinfo=tehran)
        morning_trade = datetime(2026, 9, 3, 11, 0, tzinfo=tehran)
        next_day_trade = datetime(2026, 9, 4, 11, 0, tzinfo=tehran)

        price(100, pub - timedelta(hours=2))
        evaluation(pub)
        price(150, morning_trade)
        price(200, next_day_trade)

        backtest_predictions(windows=(1,))
        outcome = PredictionOutcome.objects.get(window_trading_days=1)
        assert outcome.realized_price == Decimal("200.0000")


class TestDirection:
    def test_a_correct_up_call_is_scored_correct(self, price, evaluation):
        now = timezone.now()
        price(100, now - timedelta(hours=1))
        evaluation(now, trend=GoldTrend.UP)
        price(110, now + timedelta(days=1))
        backtest_predictions(windows=(1,))
        outcome = PredictionOutcome.objects.get()
        assert outcome.direction_correct is True
        assert outcome.realized_pct == pytest.approx(10.0)

    def test_a_wrong_up_call_is_scored_wrong(self, price, evaluation):
        now = timezone.now()
        price(100, now - timedelta(hours=1))
        evaluation(now, trend=GoldTrend.UP)
        price(90, now + timedelta(days=1))
        backtest_predictions(windows=(1,))
        assert PredictionOutcome.objects.get().direction_correct is False

    def test_a_move_inside_the_deadband_is_not_a_hit(self, price, evaluation):
        """A model that said «↑» and got +0.05% was not right. Counting it would make any
        directional accuracy number meaningless."""
        now = timezone.now()
        price(100, now - timedelta(hours=1))
        evaluation(now, trend=GoldTrend.UP)
        price(Decimal("100.05"), now + timedelta(days=1))
        backtest_predictions(windows=(1,))
        outcome = PredictionOutcome.objects.get()
        assert outcome.realized_pct < DIRECTION_DEADBAND_PCT
        assert outcome.direction_correct is False

    @pytest.mark.parametrize("trend", [GoldTrend.NEUTRAL, GoldTrend.UNCERTAIN, None])
    def test_an_admitted_unknown_is_not_a_wrong_answer(self, price, evaluation, trend):
        """«خنثی» and «نامطمئن» make no directional claim. Scoring them False would train
        the metric to punish the model for being honest."""
        now = timezone.now()
        price(100, now - timedelta(hours=1))
        evaluation(now, trend=trend)
        price(150, now + timedelta(days=1))
        backtest_predictions(windows=(1,))
        outcome = PredictionOutcome.objects.get()
        assert outcome.direction_correct is None
        assert outcome.realized_pct == pytest.approx(50.0), "the move is still recorded"


class TestScope:
    def test_evaluations_that_declined_the_gold_axis_are_not_scored(
        self, price, make_article, variant
    ):
        """A NULL gold axis made no claim about gold. Scoring it would measure the model
        against a prediction it explicitly declined to make."""
        from inference.models import Evaluation

        now = timezone.now()
        price(100, now - timedelta(hours=1))
        price(150, now + timedelta(days=1))
        Evaluation.objects.create(
            article=make_article(published_at=now),
            variant=variant,
            prompt_version=variant.prompt_version,
            provider="gapgpt",
            model="m",
            confidence_occurrence="زیاد",
            security_relevance="زیاد",
        )
        backtest_predictions(windows=(1,))
        assert PredictionOutcome.objects.count() == 0

    def test_undated_articles_are_not_scored(self, price, make_article, variant):
        from inference.models import Evaluation

        now = timezone.now()
        price(100, now - timedelta(days=1))
        price(150, now + timedelta(days=1))
        Evaluation.objects.create(
            article=make_article(published_at=None),
            variant=variant,
            prompt_version=variant.prompt_version,
            provider="gapgpt",
            model="m",
            confidence_occurrence="زیاد",
            gold_price_impact="زیاد",
            gold_trend=GoldTrend.UP,
        )
        backtest_predictions(windows=(1,))
        assert PredictionOutcome.objects.count() == 0

    def test_rescoring_updates_rather_than_duplicates(self, price, evaluation):
        now = timezone.now()
        price(100, now - timedelta(hours=1))
        evaluation(now)
        price(110, now + timedelta(days=1))
        backtest_predictions(windows=(1,))
        backtest_predictions(windows=(1,))
        assert PredictionOutcome.objects.count() == 1


class TestFeedParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("2,163,000", Decimal("2163000")), ("4,309.90", Decimal("4309.90")), ("225387000", Decimal("225387000"))],
    )
    def test_thousands_separators_are_stripped(self, raw, expected):
        assert parse_price(raw) == expected

    def test_persian_digits_are_folded(self):
        assert parse_price("۱۲۳۴") == Decimal("1234")

    @pytest.mark.parametrize("raw", ["", None, "n/a", "--"])
    def test_unparseable_price_is_none_not_zero(self, raw):
        """Storing zero for an unreadable price would show up in the back-test as a -100%
        move and read as a market crash."""
        assert parse_price(raw) is None

    def test_timestamps_are_tehran_local_not_utc(self):
        """The feed publishes Tehran local time with no offset. Reading it as UTC shifts
        every observation by three and a half hours and misaligns every window."""
        moment = parse_timestamp("2026-09-02 14:38:42")
        assert moment is not None
        assert moment.utcoffset().total_seconds() == pytest.approx(3.5 * 3600)

    @pytest.mark.parametrize("raw", ["", None, "not-a-date"])
    def test_unparseable_timestamp_is_none(self, raw):
        assert parse_timestamp(raw) is None


class TestSnapshotIdentity:
    def test_republished_stale_values_do_not_create_duplicate_rows(self):
        """TGJU republishes a closed market's last trade on every poll. Treating each poll
        as a new observation would manufacture a flat price series out of no trading."""
        moment = timezone.now()
        PriceSnapshot.objects.create(symbol=GOLD, price=100, observed_at=moment)
        from market.tasks import poll_prices  # noqa: F401  (import proves wiring)

        _, created = PriceSnapshot.objects.get_or_create(
            symbol=GOLD, observed_at=moment, defaults={"price": 100}
        )
        assert created is False
        assert PriceSnapshot.objects.count() == 1
