"""Portfolio price client: unavailable is a state, not an exception."""

from unittest.mock import MagicMock, patch

import pytest
import requests
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from market import portfolio

CONFIGURED = {
    "PORTFOLIO_MARKET_BASE_URL": "http://portfolio-frontend",
    "PORTFOLIO_MARKET_SERVICE_KEY": "k",
    "PORTFOLIO_MARKET_HOST": "portfolio.example.com",
}


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _response(payload, status=200):
    response = MagicMock(status_code=status)
    response.json.return_value = payload
    response.raise_for_status.side_effect = (
        requests.HTTPError(str(status)) if status >= 400 else None
    )
    return response


@override_settings(PORTFOLIO_MARKET_BASE_URL="", PORTFOLIO_MARKET_SERVICE_KEY="")
def test_unset_config_is_reported_without_a_request():
    with patch("market.portfolio.requests.get") as get:
        assert portfolio.catalog() == {"available": False, "reason": "not_configured"}
        assert portfolio.series("brent")["caveats"] == ["portfolio_feed_unavailable"]
    get.assert_not_called()


@override_settings(**CONFIGURED)
def test_series_sends_the_key_maps_legacy_names_and_caches():
    payload = {"key": "tedpix", "points": [{"observed_at": "2026-10-01T00:00:00+03:30",
                                            "price": "1"}], "caveats": []}
    with patch("market.portfolio.requests.get", return_value=_response(payload)) as get:
        first = portfolio.series("tehran_index", days=7)
        second = portfolio.series("tehran_index", days=7)
    assert first == second and first["available"] is True
    assert get.call_count == 1
    _, kwargs = get.call_args
    assert get.call_args.args[0] == "http://portfolio-frontend/api/marketdata/news/series/"
    assert kwargs["params"]["key"] == "tedpix"
    assert kwargs["headers"]["X-News-Service-Key"] == "k"
    assert kwargs["headers"]["Host"] == "portfolio.example.com"


@override_settings(**CONFIGURED)
def test_rejected_and_unreachable_are_distinct_and_not_cached():
    with patch("market.portfolio.requests.get", return_value=_response({}, 403)):
        assert portfolio.catalog()["reason"] == "rejected"
    with patch("market.portfolio.requests.get", side_effect=requests.ConnectTimeout()):
        assert portfolio.catalog()["reason"] == "unreachable"
    with patch("market.portfolio.requests.get", return_value=_response({"results": []})):
        assert portfolio.catalog()["available"] is True


@pytest.mark.django_db
@override_settings(PORTFOLIO_MARKET_BASE_URL="", PORTFOLIO_MARKET_SERVICE_KEY="")
def test_macro_endpoint_renders_an_empty_state_when_not_connected():
    response = APIClient().get("/api/public/macro/")
    assert response.status_code == 200
    assert response.data == {"available": False, "reason": "not_configured", "groups": []}


@pytest.mark.django_db
@override_settings(**CONFIGURED)
def test_macro_endpoint_groups_tiles_with_quotes_and_sparklines():
    catalog = {
        "groups": {"global_commodities": {"name_fa": "کالا", "name_en": "Commodities"}},
        "results": [{"key": "brent", "group": "global_commodities", "name_fa": "نفت برنت",
                     "name_en": "Brent", "unit": "USD/bbl", "currency": "USD"}],
    }
    snapshot = {"results": [{"key": "brent", "price": "99.8", "change_pct": "-2.4",
                             "observed_at": "2026-10-02T14:15:37+03:30", "caveats": []}]}
    series = {"provider": "TGJU", "caveats": [], "points": [
        {"observed_at": "2026-10-01T00:00:00+03:30", "price": "98"},
        {"observed_at": "2026-10-02T00:00:00+03:30", "price": "102"}]}

    def fake_get(url, **kwargs):
        if url.endswith("/catalog/"):
            return _response(catalog)
        if url.endswith("/snapshot/"):
            return _response(snapshot)
        return _response(series)

    with patch("market.portfolio.requests.get", side_effect=fake_get):
        body = APIClient().get("/api/public/macro/", {"key": "brent"}).data
    tile = body["groups"][0]["tiles"][0]
    assert tile["price"] == "99.8" and tile["spark"] == ["98", "102"]
    assert body["selected"]["key"] == "brent" and len(body["selected"]["points"]) == 2


@pytest.mark.django_db
@override_settings(NEWS_MARKET_SOURCE="portfolio", **CONFIGURED)
def test_market_source_portfolio_routes_tgju_symbols_through_portfolio(user):
    series = {"provider": "Portfolio", "caveats": [], "points": [
        {"observed_at": "2026-10-01T00:00:00+03:30", "price": "98"}]}
    client = APIClient()
    client.force_authenticate(user)
    with patch("market.portfolio.requests.get", return_value=_response(series)) as get:
        timeline = client.get("/api/public/assets/gold_18k/timeline/").data
        market = client.get("/api/market/", {"symbol": "gold_18k"}).data
    assert get.call_args.kwargs["params"]["key"] == "gold_18k"
    assert [str(p["price"]) for p in timeline["points"]] == ["98"]
    assert market["source"] == "portfolio" and str(market["latest"]["price"]) == "98"
