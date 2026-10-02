"""Client for the Portfolio app's price contract (`/api/marketdata/news/*`).

Portfolio owns prices; this app only reads them. Every call returns a dict with
`available`: when the base URL or key is unset, or Portfolio does not answer,
callers get `available: False` and a reason instead of an exception, so a page
can render "price service not connected" rather than a 500.

Responses are cached briefly in the Django cache (Redis in production) so one
dashboard render does not fan out to Portfolio on every request.
"""

from __future__ import annotations

from datetime import date, timedelta

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

TIMEOUT = (3, 8)
CATALOG_TTL = 60 * 60
SNAPSHOT_TTL = 60
SERIES_TTL = 10 * 60

#: Keys the reader timeline used against the retired `shared-series` endpoint.
LEGACY_KEYS = {"tehran_index": "tedpix", "bitcoin": "btc_usd", "oil": "brent"}


def configured() -> bool:
    return bool(settings.PORTFOLIO_MARKET_BASE_URL and settings.PORTFOLIO_MARKET_SERVICE_KEY)


def _unavailable(reason: str, **extra) -> dict:
    return {"available": False, "reason": reason, **extra}


def _get(path: str, params: dict, cache_key: str, ttl: int) -> dict:
    if not configured():
        return _unavailable("not_configured")
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    headers = {
        "X-News-Service-Key": settings.PORTFOLIO_MARKET_SERVICE_KEY,
        # Portfolio redirects plain HTTP to HTTPS unless its proxy says otherwise; on the
        # Docker network there is no TLS hop to say it for us.
        "X-Forwarded-Proto": "https",
    }
    if settings.PORTFOLIO_MARKET_HOST:
        headers["Host"] = settings.PORTFOLIO_MARKET_HOST
    try:
        response = requests.get(
            settings.PORTFOLIO_MARKET_BASE_URL.rstrip("/") + path,
            params=params,
            headers=headers,
            timeout=TIMEOUT,
            allow_redirects=False,
        )
        if response.status_code in {401, 403}:
            return _unavailable("rejected")
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        # Not cached: the next render retries instead of pinning an outage for minutes.
        return _unavailable("unreachable")
    if not isinstance(payload, dict):
        return _unavailable("unreachable")
    result = {"available": True, **payload}
    cache.set(cache_key, result, ttl)
    return result


def catalog() -> dict:
    return _get("/api/marketdata/news/catalog/", {}, "portfolio:catalog", CATALOG_TTL)


def snapshot(keys: list[str] | None = None) -> dict:
    keys = sorted(keys or [])
    joined = ",".join(keys)
    return _get(
        "/api/marketdata/news/snapshot/",
        {"keys": joined} if joined else {},
        f"portfolio:snapshot:{joined or 'all'}",
        SNAPSHOT_TTL,
    )


def series(key: str, *, days: int = 30, until: date | None = None, interval: str = "1d") -> dict:
    key = LEGACY_KEYS.get(key, key)
    until = until or timezone.now().date()
    since = until - timedelta(days=days)
    result = _get(
        "/api/marketdata/news/series/",
        {"key": key, "from": since.isoformat(), "to": until.isoformat(), "interval": interval},
        f"portfolio:series:{key}:{since}:{until}:{interval}",
        SERIES_TTL,
    )
    if not result["available"]:
        result = {**result, "points": [], "caveats": ["portfolio_feed_unavailable"]}
    return result
