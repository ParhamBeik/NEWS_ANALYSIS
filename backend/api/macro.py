"""Public macro dashboard: Portfolio's curated prices as tiles, sparklines and one chart.

Transport only: it asks `market.portfolio` and reshapes. When Portfolio is not
configured or not answering, the response says so (`available: false`) and the
page renders an empty state; it never invents a price.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from django.utils import timezone
from rest_framework.response import Response

from market import portfolio

from .public import ReaderView

SPARK_DAYS = 30
CHART_DAYS = 30


def _spark(key: str) -> list[str]:
    return [row["price"] for row in portfolio.series(key, days=SPARK_DAYS).get("points", [])]


class PublicMacroView(ReaderView):
    def get(self, request):
        catalog = portfolio.catalog()
        if not catalog["available"]:
            return Response({"available": False, "reason": catalog["reason"], "groups": []})
        rows = catalog.get("results", [])
        keys = [row["key"] for row in rows]
        snapshot = portfolio.snapshot(keys)
        quotes = {row["key"]: row for row in snapshot.get("results", [])}
        # Sparklines are one series each; Portfolio caches them, and so do we, so this
        # fan-out is paid once per cache window, in parallel, not once per reader.
        with ThreadPoolExecutor(max_workers=8) as pool:
            sparks = dict(zip(keys, pool.map(_spark, keys), strict=True))

        groups = []
        for group_key, names in catalog.get("groups", {}).items():
            tiles = []
            for row in rows:
                if row["group"] != group_key:
                    continue
                quote = quotes.get(row["key"], {})
                tiles.append({
                    **{k: row.get(k) for k in ("key", "name_fa", "name_en", "unit", "currency",
                                               "asset_class", "cadence", "market_hours")},
                    "price": quote.get("price"),
                    "change_pct": quote.get("change_pct"),
                    "observed_at": quote.get("observed_at"),
                    "caveats": quote.get("caveats", ["portfolio_feed_unavailable"]),
                    "spark": sparks.get(row["key"], []),
                })
            groups.append({"key": group_key, **names, "tiles": tiles})

        selected_key = request.query_params.get("key")
        if selected_key not in keys:
            selected_key = "brent" if "brent" in keys else (keys[0] if keys else None)
        selected = None
        if selected_key:
            chart = portfolio.series(selected_key, days=CHART_DAYS)
            meta = next(row for row in rows if row["key"] == selected_key)
            selected = {
                "key": selected_key, "name_fa": meta["name_fa"], "name_en": meta["name_en"],
                "unit": meta["unit"], "currency": meta["currency"],
                "provider": chart.get("provider"),
                "points": [{"observed_at": p["observed_at"], "price": p["price"]}
                           for p in chart.get("points", [])],
                "caveats": chart.get("caveats", []),
            }
        return Response({
            "available": True,
            "snapshot_available": snapshot["available"],
            "as_of": timezone.now(),
            "groups": groups,
            "selected": selected,
        })
