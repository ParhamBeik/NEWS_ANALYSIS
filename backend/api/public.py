"""Public reader API. Full article bodies and operator data never cross this boundary."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from itertools import pairwise
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from articles.models import AlertSubscription, NewsEvent, StorylineEvent
from core import tiers
from core.events import ranked_events
from core.vocabulary import event_topic
from market import portfolio
from market.models import PriceSnapshot, Symbol
from sources.models import Source


class ReaderThrottle(AnonRateThrottle):
    scope = "reader"


class ReaderView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ReaderThrottle]


class AlertThrottle(UserRateThrottle):
    scope = "alert_subscription"


class AlertConfigView(ReaderView):
    def get(self, request):
        enabled = bool(
            settings.NEWS_ALERTS_ENABLED
            and settings.NEWS_VAPID_PUBLIC_KEY
            and settings.NEWS_VAPID_PRIVATE_KEY
            and settings.NEWS_VAPID_SUBJECT
        )
        return Response(
            {"enabled": enabled, "public_key": settings.NEWS_VAPID_PUBLIC_KEY if enabled else ""}
        )


class AlertSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [AlertThrottle]

    def post(self, request):
        subscription = request.data.get("subscription") or {}
        endpoint = subscription.get("endpoint", "") if isinstance(subscription, dict) else ""
        keys = subscription.get("keys") or {} if isinstance(subscription, dict) else {}
        hostname = urlsplit(endpoint).hostname if isinstance(endpoint, str) else None
        allowed = hostname in {
            "fcm.googleapis.com",
            "updates.push.services.mozilla.com",
            "web.push.apple.com",
        } or (bool(hostname) and hostname.endswith(".push.apple.com"))
        if not (
            settings.NEWS_ALERTS_ENABLED
            and settings.NEWS_VAPID_PUBLIC_KEY
            and settings.NEWS_VAPID_PRIVATE_KEY
            and settings.NEWS_VAPID_SUBJECT
        ):
            raise ValidationError({"subscription": "browser alerts are not configured"})
        if (
            not isinstance(endpoint, str)
            or not endpoint.startswith("https://")
            or not allowed
            or len(endpoint) > 2048
            or not isinstance(keys, dict)
            or not all(
                isinstance(keys.get(name), str) and 20 <= len(keys[name]) <= 255
                for name in ("p256dh", "auth")
            )
        ):
            raise ValidationError({"subscription": "invalid browser push subscription"})
        assets = request.data.get("asset_classes") or []
        if (
            not isinstance(assets, list)
            or len(assets) > 5
            or any(
                value not in {"fx", "gold", "tehran_index", "oil", "bitcoin"} for value in assets
            )
        ):
            raise ValidationError({"asset_classes": "invalid asset interests"})
        # A browser endpoint cannot be claimed by a different signed-in user.
        row = AlertSubscription.objects.filter(endpoint=endpoint).first()
        if row and row.user_id != request.user.id:
            raise ValidationError({"subscription": "endpoint already registered"})
        AlertSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                "user": request.user,
                "p256dh": keys["p256dh"],
                "auth": keys["auth"],
                "iran": bool(request.data.get("iran", True)),
                "global_events": bool(request.data.get("global_events", False)),
                "asset_classes": assets,
            },
        )
        return Response({"subscribed": True})

    def delete(self, request):
        endpoint = request.data.get("endpoint", "")
        AlertSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
        return Response(status=204)


def event_document(event: NewsEvent, *, detail: bool = False, cuts: dict | None = None) -> dict:
    articles = sorted(event.articles.all(), key=lambda row: row.published_at or row.fetched_at)
    primary = event.primary_article
    image = getattr(primary, "image", None)
    allowed = bool(image) and primary.source.public_image_allowed
    # One stored copy serves card and hero (docs/STORAGE-POLICY.md); legacy rows may
    # still have a separate thumbnail. Same permission gate for both.
    card = (image.thumbnail or image.file) if allowed else None
    permitted_image = card.url if card else None
    permitted_large = image.file.url if allowed and image.file else None
    latest = max(event.assessments.all(), key=lambda row: row.id, default=None)
    asset_scores = latest.asset_scores if latest else {}
    document = {
        "id": event.id,
        "status": event.status,
        "evidence_level": event.evidence_level,
        "category": event_topic(event.category) or None,
        "title": event.title_fa or primary.original_title,
        "title_fa": event.title_fa or None,
        "title_en": event.title_en or None,
        "original_title": primary.original_title,
        "brief_fa": event.brief_fa or None,
        "brief_en": event.brief_en or None,
        "channels_fa": event.channels_fa or None,
        "channels_en": event.channels_en or None,
        "uncertainty_fa": event.uncertainty_fa or None,
        "uncertainty_en": event.uncertainty_en or None,
        "iran_score": event.iran_score,
        "global_score": event.global_score,
        # Tiers 1-5 are decided here (core.tiers), never recomputed by the reader.
        "iran_tier": tiers.tier(event.iran_score, "iran", cuts),
        "global_tier": tiers.tier(event.global_score, "global", cuts),
        "impact_tier": tiers.tier(
            tiers.impact(event.iran_score, event.global_score), "impact", cuts
        ),
        "asset_scores": asset_scores,
        "asset_tiers": {key: tiers.band(value) for key, value in asset_scores.items()},
        "assessment_confidence": event.assessment_confidence,
        "watch_items": [
            {
                "slug": link.item.slug,
                "kind": link.item.kind,
                "name_fa": link.item.name_fa,
                "name_en": link.item.name_en,
            }
            for link in sorted(event.watch_links.all(), key=lambda row: row.id)
        ],
        "event_time": event.event_time,
        "first_seen_at": event.first_seen_at,
        "image_url": permitted_image,
        "image_large_url": permitted_large or permitted_image,
        "sources": [
            {
                "name": a.source.display_name or a.source_id,
                "original_outlet": a.original_outlet or None,
                "url": a.url,
                "published_at": a.published_at,
                "first_seen_at": a.created_at,
                "date_uncertain": a.date_uncertain,
                "status": a.url_status,
                **({"headline": a.original_title, "lead": a.lead[:500]} if detail else {}),
            }
            for a in articles
        ],
    }
    if detail:
        link = (
            StorylineEvent.objects.filter(event=event).select_related("storyline").first()
        )
        document["storyline"] = (
            {
                "id": link.storyline_id,
                "name_fa": link.storyline.name_fa,
                "name_en": link.storyline.name_en,
                "events": [
                    {
                        "id": row.id,
                        "title_fa": row.title_fa or row.primary_article.original_title,
                        "title_en": row.title_en or None,
                        "event_time": row.event_time,
                    }
                    for row in NewsEvent.objects.filter(storyline_link__storyline=link.storyline)
                    .exclude(status=NewsEvent.Status.WITHDRAWN)
                    .select_related("primary_article")
                    .order_by("event_time", "id")[:20]
                ],
            }
            if link
            else None
        )
        document["history"] = sorted(
            [
                {"source": article.source.display_name or article.source_id,
                 "previous_headline": revision.title,
                 "previous_status": revision.status,
                 "observed_at": revision.observed_at}
                for article in articles for revision in article.revisions.all()
            ],
            key=lambda row: row["observed_at"], reverse=True,
        )[:20]
    return document


class PublicEventsView(ReaderView):
    def get(self, request):
        period = request.query_params.get("period", "now")
        mode = request.query_params.get("mode", "ranked")
        if period not in {"now", "today", "week", "latest"}:
            raise ValidationError({"period": "choose now, today, week, or latest"})
        if mode not in {"ranked", "latest"}:
            raise ValidationError({"mode": "choose ranked or latest"})
        now = timezone.now()
        local = now.astimezone(ZoneInfo(settings.TEHRAN_TZ))
        since = {
            "now": now - timedelta(hours=24),
            "today": local.replace(hour=0, minute=0, second=0, microsecond=0),
            "week": now - timedelta(days=7),
            "latest": now - timedelta(days=30),
        }[period]
        queryset = (
            NewsEvent.objects.filter(event_time__gte=since)
            .filter(primary_article__prefilter_reason="", primary_article__quality_flag="")
            .exclude(category="other")
            .exclude(status=NewsEvent.Status.WITHDRAWN)
            .select_related("primary_article__source", "primary_article__image")
            .prefetch_related("articles__source", "assessments", "watch_links__item")
            .order_by("-event_time", "-id")[:300]
        )
        events = list(queryset)
        if mode == "ranked" and period != "latest":
            events = ranked_events(events, now)
        cuts = tiers.cutoffs()
        return Response(
            {"results": [event_document(e, cuts=cuts) for e in events[:50]], "as_of": now}
        )


class PublicEventDetailView(ReaderView):
    def get(self, request, event_id: int):
        event = (
            NewsEvent.objects.select_related("primary_article__source", "primary_article__image")
            .prefetch_related(
                "articles__source", "articles__revisions", "assessments", "watch_links__item"
            )
            .filter(primary_article__prefilter_reason="", primary_article__quality_flag="")
            .filter(pk=event_id)
            .first()
        )
        if event is None:
            raise NotFound()
        return Response(event_document(event, detail=True))


class PublicSourcesView(ReaderView):
    def get(self, request):
        return Response(
            {
                "results": [
                    {
                        "name": row.name,
                        "display_name": row.display_name,
                        "health": row.health_status,
                        "last_success_at": row.last_success_at,
                    }
                    for row in Source.objects.filter(enabled=True).order_by("priority")
                ]
            }
        )


ASSETS = {
    "usd_irr": {
        "name": "USD / IRR",
        "name_fa": "دلار",
        "class": "fx",
        "unit": "IRR",
        "provider": "TGJU",
    },
    "gold_18k": {
        "name": "18K gold",
        "name_fa": "طلای ۱۸ عیار",
        "class": "gold",
        "unit": "IRR",
        "provider": "TGJU",
    },
    "gold_ounce": {
        "name": "Gold ounce",
        "name_fa": "انس جهانی",
        "class": "gold",
        "unit": "USD",
        "provider": "TGJU",
    },
    "coin_emami": {
        "name": "Emami coin",
        "name_fa": "سکه امامی",
        "class": "gold",
        "unit": "IRR",
        "provider": "TGJU",
    },
    "eur_irr": {
        "name": "EUR / IRR",
        "name_fa": "یورو",
        "class": "fx",
        "unit": "IRR",
        "provider": "TGJU",
    },
}

SHARED_ASSETS = {
    "tehran_index": {
        "name": "Tehran overall index",
        "name_fa": "شاخص کل تهران",
        "class": "tehran_index",
        "unit": "points",
        "provider": "Portfolio warehouse",
    },
    "bitcoin": {
        "name": "Bitcoin",
        "name_fa": "بیت‌کوین",
        "class": "bitcoin",
        "unit": "USDT",
        "provider": "Portfolio warehouse",
    },
    "oil": {
        "name": "Brent oil",
        "name_fa": "نفت برنت",
        "class": "oil",
        "unit": "provider quote",
        "provider": "Portfolio warehouse",
    },
}


def available_assets():
    return {
        **ASSETS,
        **(
            SHARED_ASSETS
            if settings.PORTFOLIO_MARKET_BASE_URL and settings.PORTFOLIO_MARKET_SERVICE_KEY
            else {}
        ),
    }


class PublicAssetsView(ReaderView):
    def get(self, request):
        return Response(
            {
                "results": [{"key": key, **value} for key, value in ASSETS.items()]
                + [
                    {"key": key, **value}
                    for key, value in available_assets().items()
                    if key not in ASSETS
                ]
            }
        )


class PublicTimelineView(ReaderView):
    def get(self, request, symbol: str):
        catalog = available_assets()
        if symbol not in catalog:
            raise NotFound("Unknown asset")
        window = request.query_params.get("range", "1M")
        days = {"1W": 7, "1M": 30, "3M": 90, "1Y": 365}.get(window)
        if days is None:
            raise ValidationError({"range": "choose 1W, 1M, 3M, or 1Y"})
        all_events = request.query_params.get("events") == "all"
        since = timezone.now() - timedelta(days=days)
        caveats = []
        asset = {"key": symbol, **catalog[symbol]}
        if symbol in Symbol.values:
            points = list(
                PriceSnapshot.objects.filter(
                    symbol=symbol,
                    observed_at__gte=since,
                )
                .order_by("observed_at")
                .values("observed_at", "price", "fetched_at")
            )
            points = [
                {
                    **point,
                    "provider": "TGJU",
                    "quality": "provider_observation",
                    "time_precision": "feed_timestamp",
                }
                for point in points
            ]
        else:
            remote = _shared_series(symbol, days)
            points = remote["points"]
            caveats = remote["caveats"]
            asset.update(
                unit=remote.get("unit") or asset["unit"],
                provider=remote.get("provider") or asset["provider"],
            )
        events = list(
            NewsEvent.objects.filter(event_time__gte=since)
            .filter(primary_article__prefilter_reason="", primary_article__quality_flag="")
            .exclude(category="other")
            .exclude(status=NewsEvent.Status.WITHDRAWN)
            .select_related("primary_article__source")
            .prefetch_related("articles__source", "assessments", "watch_links__item")
            .order_by("event_time")[:500]
        )
        asset_class = asset["class"]
        markers = []
        cuts = tiers.cutoffs()
        for event in events:
            document = event_document(event, cuts=cuts)
            relevance = document["asset_scores"].get(asset_class)
            if not all_events and (relevance is None or relevance < 50):
                continue
            markers.append(
                {
                    "event": document,
                    "relevance": relevance,
                    "observed_changes": _observed_changes(points, event.event_time),
                }
            )
        return Response(
            {
                "asset": asset,
                "range": window,
                "resolution": remote.get("resolution", "observations")
                if symbol not in Symbol.values
                else "observations",
                "as_of": timezone.now(),
                "points": points,
                "events": markers,
                "last_observation_at": points[-1]["observed_at"] if points else None,
                "gaps": [
                    {"after": previous["observed_at"], "before": current["observed_at"]}
                for previous, current in pairwise(points)
                    if current["observed_at"] - previous["observed_at"] > timedelta(days=3)
                ],
                "caveats": (
                    caveats
                    + (
                        ["stale_or_closed_market"]
                        if points and timezone.now() - points[-1]["observed_at"] > timedelta(days=3)
                        else []
                    )
                )
                if points
                else caveats or ["no_price_observations"],
            }
        )


def _shared_series(symbol: str, days: int) -> dict:
    cache_key = f"newsintel:shared-market:{symbol}:{days}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        payload = portfolio.series(symbol, days=days)
        if not payload["available"]:
            return {"points": [], "caveats": payload["caveats"], "resolution": "unknown"}
        points = []
        for row in payload.get("points", []):
            if not row.get("observed_at") or row.get("price") is None:
                continue
            observed = parse_datetime(row["observed_at"])
            price = Decimal(str(row["price"]))
            if (
                observed is None
                or timezone.is_naive(observed)
                or not price.is_finite()
                or price <= 0
            ):
                continue
            points.append(
                {
                    "observed_at": observed,
                    "price": price,
                    "quality": row.get("quality"),
                    "provider": row.get("provider"),
                    "time_precision": row.get("time_precision"),
                }
            )
        points.sort(key=lambda row: row["observed_at"])
        result = {
            "points": points,
            "caveats": payload.get("caveats", []),
            "provider": payload.get("provider"),
            "unit": payload.get("unit"),
            "resolution": payload.get("resolution", "daily"),
        }
        cache.set(cache_key, result, 60)
        return result
    except (requests.RequestException, ValueError, KeyError, TypeError, ArithmeticError):
        return {"points": [], "caveats": ["portfolio_feed_unavailable"], "resolution": "unknown"}


def _observed_changes(points: list[dict], event_time) -> dict:
    baseline = next((row for row in reversed(points) if row["observed_at"] <= event_time), None)
    if (
        baseline is None
        or not baseline["price"]
        or event_time - baseline["observed_at"] > timedelta(days=3)
    ):
        return {}
    results = {}
    for label, duration in (("1d", timedelta(days=1)), ("1w", timedelta(days=7))):
        target = event_time + duration
        if target > timezone.now():
            continue
        later = next(
            (row for row in points if target <= row["observed_at"] <= target + timedelta(days=3)),
            None,
        )
        if later is None:
            continue
        results[label] = {
            "percent": round(100 * (later["price"] - baseline["price"]) / baseline["price"], 2),
            "baseline_at": baseline["observed_at"],
            "later_at": later["observed_at"],
            "label": "Observed association, not causal impact",
        }
    return results
