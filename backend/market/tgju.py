"""TGJU price feed.

TGJU publishes a single JSON document with ~963 keys covering gold, currencies, crypto and
commodities. We track five series; the rest is noise for this purpose.

Two things about this feed that shape the code:

1. It republishes stale values. A closed market still appears in every response, carrying
   the timestamp of its LAST TRADE. `observed_at` is therefore the feed's own timestamp,
   never our fetch time - otherwise polling a closed market every 15 minutes manufactures
   a flat price series out of no trading at all, and the back-test would read that as
   "gold did not move" rather than "gold was not trading".
2. Prices arrive as display strings with thousands separators ("2,163,000"), and Persian
   digits appear in some fields. Both are normalised before parsing.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.conf import settings

from core.errors import Permanent, Transient
from core.text import fold
from sources.extraction import build_session

from .models import Symbol

FEED_URL = "https://call1.tgju.org/ajax.json"

# Our symbol -> the key TGJU publishes it under. Kept explicit rather than pattern-matched:
# the feed contains several near-identical keys per metal and picking the wrong one is a
# silent, plausible-looking error.
KEY_MAP = {
    Symbol.GOLD_18K: "geram18",
    Symbol.GOLD_OUNCE: "ons",
    Symbol.COIN_EMAMI: "sekee",
    Symbol.USD_IRR: "price_dollar_rl",
    Symbol.EUR_IRR: "price_eur",
}

logger = logging.getLogger(__name__)


def parse_price(raw: object) -> Decimal | None:
    """"2,163,000" -> Decimal. Persian digits and separators are folded out first."""
    text = fold(str(raw or "")).replace(",", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_timestamp(raw: object) -> datetime | None:
    """TGJU's `ts` field is Tehran local time with no offset. Attaching UTC would shift
    every observation by three and a half hours and quietly misalign the back-test."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        naive = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=ZoneInfo(settings.TEHRAN_TZ))


def fetch(session=None) -> dict[str, dict]:
    """Pull the feed and return only the series we track, parsed."""
    session = session or build_session()
    try:
        response = session.get(FEED_URL, timeout=settings.NEWS_HTTP_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except ValueError as exc:
        raise Permanent(f"TGJU feed is not JSON: {exc}") from exc
    except Exception as exc:
        raise Transient(f"TGJU fetch failed: {exc}") from exc

    current = payload.get("current")
    if not isinstance(current, dict):
        raise Permanent("TGJU feed has no `current` object")

    parsed: dict[str, dict] = {}
    for symbol, key in KEY_MAP.items():
        entry = current.get(key)
        if not isinstance(entry, dict):
            logger.warning("TGJU key %r missing for %s", key, symbol)
            continue
        price = parse_price(entry.get("p"))
        observed_at = parse_timestamp(entry.get("ts"))
        if price is None or observed_at is None:
            logger.warning(
                "TGJU %s unparseable: price=%r ts=%r", symbol, entry.get("p"), entry.get("ts")
            )
            continue
        parsed[symbol] = {"price": price, "observed_at": observed_at}
    return parsed
