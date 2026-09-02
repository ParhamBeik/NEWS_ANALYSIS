"""Price polling and the prediction back-test.

The back-test is the only quality signal in this system that needs no human. Every other
metric waits on someone sitting in front of /review; this one just asks whether the market
did what the model said it would.

That makes it valuable and makes it easy to get flatteringly wrong, so three choices are
deliberate:

1. The baseline is the last price observed BEFORE publication. Using the first price after
   would fold the very move being predicted into the baseline and report near-zero error.
2. Windows are counted in TRADING days, not calendar days. The Iranian gold market closes
   on Fridays and public holidays; a naive 24-hour window scores every Thursday-evening
   prediction against a frozen price and reports "no movement", which quietly inflates the
   model's apparent calibration on exactly the quiet days it should be judged least on.
3. «خنثی» and «نامطمئن» score as `direction_correct = None`, not False. An admitted
   unknown is not a wrong answer, and counting it as one would train the metric to punish
   the model for being honest - which is the opposite of what this pipeline needs.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.db import IntegrityError

from core.errors import Transient
from core.vocabulary import GoldTrend

from . import tgju
from .models import PredictionOutcome, PriceSnapshot, Symbol

logger = logging.getLogger(__name__)

# Below this the move is noise, not a direction. A model that said «↑» and got +0.05%
# was not right; it was not wrong either, and scoring it as a hit would make any
# directional accuracy number meaningless.
DIRECTION_DEADBAND_PCT = 0.25

DEFAULT_WINDOWS = (1, 3)


@shared_task(
    name="market.poll_prices",
    autoretry_for=(Transient,),
    retry_backoff=True,
    max_retries=3,
)
def poll_prices() -> dict:
    """Store one observation per tracked series, keyed on the feed's own timestamp.

    Re-polling a closed market is a no-op rather than a duplicate row: the unique
    constraint on (symbol, observed_at) is what keeps a stale republished value from
    manufacturing a flat price series.
    """
    stored, unchanged = 0, 0
    for symbol, entry in tgju.fetch().items():
        try:
            _, created = PriceSnapshot.objects.get_or_create(
                symbol=symbol,
                observed_at=entry["observed_at"],
                defaults={"price": entry["price"]},
            )
        except IntegrityError:
            created = False
        stored += created
        unchanged += not created
    return {"stored": stored, "unchanged": unchanged}


def _direction_correct(trend: str | None, realized_pct: float) -> bool | None:
    """Did the stated direction match the move? None when no direction was claimed."""
    if trend == GoldTrend.UP:
        return realized_pct > DIRECTION_DEADBAND_PCT
    if trend == GoldTrend.DOWN:
        return realized_pct < -DIRECTION_DEADBAND_PCT
    # «خنثی» and «نامطمئن»: no claim was made, so there is nothing to be right about.
    return None


def _score_one(evaluation, symbol: str, window: int) -> PredictionOutcome | None:
    article = evaluation.article
    if article.published_at is None:
        return None
    baseline = PriceSnapshot.last_before(symbol, article.published_at)
    if baseline is None or not baseline.price:
        return None
    target_at = PriceSnapshot.trading_days_after(symbol, article.published_at, window)
    if target_at is None:
        # The market has not traded that many days since publication yet. Not an error -
        # this evaluation simply is not scorable, and will be on a later sweep.
        return None
    realized = PriceSnapshot.objects.filter(symbol=symbol, observed_at=target_at).first()
    if realized is None:
        return None

    change = (float(realized.price) - float(baseline.price)) / float(baseline.price) * 100
    outcome, _ = PredictionOutcome.objects.update_or_create(
        evaluation=evaluation,
        symbol=symbol,
        window_trading_days=window,
        defaults={
            "baseline_price": baseline.price,
            "realized_price": realized.price,
            "realized_pct": round(change, 4),
            "direction_correct": _direction_correct(evaluation.gold_trend, change),
        },
    )
    return outcome


@shared_task(name="market.backtest_predictions")
def backtest_predictions(
    symbol: str = Symbol.GOLD_18K, windows: tuple[int, ...] = DEFAULT_WINDOWS, limit: int = 500
) -> dict:
    """Score every gold-impact prediction that the market has now had time to answer.

    Only evaluations that actually ASSESSED the gold axis are scored. An evaluation that
    left `gold_price_impact` NULL made no claim about gold, and including it would measure
    the model against a prediction it explicitly declined to make.
    """
    from inference.models import Evaluation

    pending = (
        Evaluation.objects.filter(gold_price_impact__isnull=False)
        .filter(article__published_at__isnull=False)
        .select_related("article")
        .order_by("-created_at")[:limit]
    )
    scored, skipped = 0, 0
    for evaluation in pending:
        for window in windows:
            if _score_one(evaluation, symbol, window) is not None:
                scored += 1
            else:
                skipped += 1
    return {"symbol": symbol, "scored": scored, "not_yet_scorable": skipped}
