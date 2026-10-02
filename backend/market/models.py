"""Market prices, and the back-test that scores gold predictions without a human.

Every other quality metric in this system needs someone to sit down and label articles.
This one does not: the model says «زیاد» gold impact and «↑» direction, and the market
either moves or it does not. It is the only ground truth available in volume.

Two things make it honest rather than flattering:

1. The Iranian gold market is CLOSED on Fridays and public holidays. A naive 24-hour
   window scores every Thursday-evening prediction against a frozen price and reports "no
   movement", which silently inflates the model's apparent calibration on quiet days.
   `PriceSnapshot.trading_days_after` walks actual observations, not the calendar.
2. The baseline is the last price observed BEFORE publication, never the first one after.
   Using the after-price folds the very move being predicted into the baseline.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from django.db import models


class Symbol(models.TextChoices):
    """The series worth tracking. Keys are ours; `tgju_key` maps them to the feed."""

    GOLD_18K = "gold_18k", "Gold, 18 carat (گرم طلای ۱۸ عیار)"
    GOLD_OUNCE = "gold_ounce", "Gold, global ounce (انس جهانی)"
    COIN_EMAMI = "coin_emami", "Emami coin (سکه امامی)"
    USD_IRR = "usd_irr", "US Dollar / Rial (دلار)"
    EUR_IRR = "eur_irr", "Euro / Rial (یورو)"


def nth_trading_day(timestamps: Iterable[datetime], start: datetime, days: int) -> datetime | None:
    """The first observation of the `days`-th trading day after `start`, or None.

    `timestamps` are observations in ascending order. A trading day is a Tehran calendar
    day with at least one observation, so no holiday calendar is needed. The start day is
    day ZERO and is skipped. Shared by the TGJU back-test and the event reactions, which
    read Portfolio series instead of PriceSnapshot rows.
    """
    from zoneinfo import ZoneInfo

    from django.conf import settings
    from django.utils import timezone

    tz = ZoneInfo(getattr(settings, "TEHRAN_TZ", "Asia/Tehran"))

    def _market_date(dt: datetime):
        return dt.astimezone(tz).date() if timezone.is_aware(dt) else dt.date()

    start_day, last_day, seen = _market_date(start), None, 0
    for observed_at in timestamps:
        if observed_at <= start:
            continue
        day = _market_date(observed_at)
        if day == start_day or day == last_day:
            continue
        last_day, seen = day, seen + 1
        if seen >= days:
            return observed_at
    return None


class PriceSnapshot(models.Model):
    """One observation. Append-only; the poller never updates a prior row.

    `observed_at` is the feed's own timestamp, not our fetch time - TGJU republishes stale
    values for closed markets, and treating a re-fetch as a new observation would
    manufacture a flat price series out of a closed market.
    """

    symbol = models.CharField(max_length=32, choices=Symbol, db_index=True)
    price = models.DecimalField(max_digits=20, decimal_places=4)
    observed_at = models.DateTimeField(db_index=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-observed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["symbol", "observed_at"], name="unique_price_observation"
            ),
        ]
        indexes = [models.Index(fields=["symbol", "-observed_at"])]

    def __str__(self) -> str:
        return f"{self.symbol} {self.price} @ {self.observed_at:%Y-%m-%d %H:%M}"

    @classmethod
    def last_before(cls, symbol: str, moment: datetime) -> PriceSnapshot | None:
        return cls.objects.filter(symbol=symbol, observed_at__lte=moment).first()

    @classmethod
    def trading_days_after(cls, symbol: str, start: datetime, days: int) -> datetime | None:
        """The timestamp `days` TRADING days after `start`, or None if the market has not
        traded that many days yet.

        A trading day is one on which this symbol actually produced a new observation. That
        definition needs no holiday calendar and stays correct when the market closes for a
        reason nobody encoded.

        The publication day is day ZERO and is skipped. Counting it made `days=1` resolve
        to the next observation - with a 15-minute poller, fifteen minutes of price
        movement scored as a one-day window - and `days=3` span about two calendar days.
        Every realised return was measured over less time than it claimed.
        """
        rows = cls.objects.filter(symbol=symbol, observed_at__gt=start).order_by("observed_at")
        return nth_trading_day(rows.values_list("observed_at", flat=True).iterator(), start, days)


class PredictionOutcome(models.Model):
    """What actually happened after an evaluation predicted a gold move.

    Deliberately NOT a score. It records the realised move and whether the stated direction
    matched; turning that into "is the model good?" is an aggregation on /kpi, where the
    sample size is visible next to it.
    """

    evaluation = models.ForeignKey(
        "inference.Evaluation", on_delete=models.CASCADE, related_name="outcomes"
    )
    symbol = models.CharField(max_length=32, choices=Symbol, default=Symbol.GOLD_18K)
    window_trading_days = models.PositiveSmallIntegerField(default=1)

    baseline_price = models.DecimalField(max_digits=20, decimal_places=4)
    realized_price = models.DecimalField(max_digits=20, decimal_places=4)
    realized_pct = models.FloatField()
    # None when the prediction was «خنثی»/«نامطمئن» - an admitted unknown is not a wrong
    # answer, and counting it as one would punish the model for being honest.
    direction_correct = models.BooleanField(null=True, blank=True)
    computed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-computed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["evaluation", "symbol", "window_trading_days"],
                name="unique_prediction_outcome",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.symbol} {self.realized_pct:+.2f}% over {self.window_trading_days}d"


class EventReaction(models.Model):
    """How one asset moved around one news event: the event-level back-test.

    Not a verdict on the model either. It records the move and how unusual it was against
    the asset's own trailing 30 days of daily moves (`abs_z`); calibration (does a higher
    tier come with bigger moves?) is an aggregation over these rows on /ops.

    Prices come from Portfolio, the single price authority. Windows: `2h` (two hours either
    side) and `1d` for 24-hour global markets; `1td` and `3td` trading days for Iranian
    markets, which close on Fridays and holidays.
    """

    event = models.ForeignKey(
        "articles.NewsEvent", on_delete=models.CASCADE, related_name="reactions"
    )
    asset_key = models.CharField(max_length=64)
    asset_class = models.CharField(max_length=32, blank=True)
    window = models.CharField(max_length=8)
    # The event's impact tier when the reaction was computed. Tiers are relative to the
    # trailing 30 days, so recomputing them later would rewrite history.
    tier = models.PositiveSmallIntegerField()
    price_before = models.DecimalField(max_digits=24, decimal_places=8)
    price_after = models.DecimalField(max_digits=24, decimal_places=8)
    pct_change = models.FloatField()
    # None when the trailing series is too short or flat to say what "usual" is.
    abs_z = models.FloatField(null=True, blank=True)
    computed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-computed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "asset_key", "window"], name="unique_event_reaction"
            ),
        ]

    def __str__(self) -> str:
        return f"event {self.event_id} {self.asset_key} {self.window} {self.pct_change:+.2f}%"
