"""eBay comparable-listings service: query building + price aggregation.

No live API (house rule): the network seam (`_ensure_token` + httpx) is stubbed,
but the query hierarchy, the degrade-to-link-only paths, and the price math all
run for real. This module previously had zero coverage.
"""

from __future__ import annotations

import pytest

from headroom.services import ebay_service

pytestmark = pytest.mark.anyio


# ----------------------------- query building -------------------------- #


async def test_build_query_prefers_brand_and_model():
    assert (
        ebay_service._build_query("Melin", "A-Game Hydro", "a_game")
        == "Melin A-Game Hydro hat"
    )


async def test_build_query_falls_back_to_style_when_no_model():
    # Style is used only when the model is absent; underscores become spaces.
    assert (
        ebay_service._build_query("Melin", None, "trucker_snapback")
        == "Melin trucker snapback hat"
    )


async def test_build_query_is_bare_when_nothing_identifying():
    assert ebay_service._build_query(None, None, None) == "hat"


async def test_browse_html_url_encodes_query():
    url = ebay_service._browse_html_url("Melin A-Game hat")
    assert url.endswith("_nkw=Melin%20A-Game%20hat")


# ------------------------ degradation (no network) --------------------- #


async def test_find_comps_no_identifiers_returns_zeroed(db_session):
    """Nothing to search on → count 0, no URL, and the network is never hit."""
    result = await ebay_service.find_comps(
        db_session, brand=None, model=None, style=None
    )
    assert result["ebay_listing_count"] == 0
    assert result["ebay_search_url"] is None
    assert result["ebay_avg_price"] is None


async def test_find_comps_without_creds_returns_link_only(db_session):
    """Default env has no eBay creds → deep link, count=None (unknown, not 0).

    The None-vs-0 distinction is load-bearing: 0 means "searched, found nothing",
    None means "never searched" — the UI renders them differently.
    """
    result = await ebay_service.find_comps(
        db_session, brand="Melin", model="A-Game Hydro", style="a_game"
    )
    assert result["ebay_listing_count"] is None
    assert result["ebay_search_url"] is not None
    assert "_nkw=" in result["ebay_search_url"]
    assert result["ebay_avg_price"] is None


# ---------------------------- price aggregation ------------------------ #


class _FakeResp:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    """Minimal async-context-manager stand-in for httpx.AsyncClient."""

    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        return _FakeResp(self._payload)


async def test_find_comps_aggregates_only_valid_positive_prices(db_session, monkeypatch):
    """avg/median are computed over parseable positive prices only, while the
    listing count is the TOTAL number of items — a zero or garbage price still
    counts as a listing but must not skew the stats."""

    async def _fake_creds(_db):
        return ("app", "cert", "EBAY_US")

    async def _fake_token(_app, _cert):
        return "tok"

    payload = {
        "itemSummaries": [
            {"price": {"value": "40.00"}},
            {"price": {"value": "50.00"}},
            {"price": {"value": "90.00"}},
            {"price": {"value": "0"}},          # non-positive → excluded from stats
            {"price": {"value": "not-a-num"}},  # unparseable → excluded from stats
        ]
    }
    monkeypatch.setattr(ebay_service, "_get_creds", _fake_creds)
    monkeypatch.setattr(ebay_service, "_ensure_token", _fake_token)
    monkeypatch.setattr(
        ebay_service.httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload)
    )

    result = await ebay_service.find_comps(
        db_session, brand="Melin", model="A-Game Hydro", style="a_game"
    )
    assert result["ebay_avg_price"] == 60.0     # mean of 40/50/90
    assert result["ebay_median_price"] == 50.0  # median of 40/50/90 (≠ the mean)
    assert result["ebay_listing_count"] == 5    # all five items, not just the 3 priced
    assert result["ebay_search_url"] is not None


async def test_find_comps_no_valid_prices_yields_none_stats(db_session, monkeypatch):
    """Items present but no usable prices → avg/median None, count still counts."""

    async def _fake_creds(_db):
        return ("app", "cert", "EBAY_US")

    async def _fake_token(_app, _cert):
        return "tok"

    payload = {"itemSummaries": [{"price": {"value": "0"}}, {"noprice": True}]}
    monkeypatch.setattr(ebay_service, "_get_creds", _fake_creds)
    monkeypatch.setattr(ebay_service, "_ensure_token", _fake_token)
    monkeypatch.setattr(
        ebay_service.httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload)
    )

    result = await ebay_service.find_comps(db_session, brand="Melin", model="X", style=None)
    assert result["ebay_avg_price"] is None
    assert result["ebay_median_price"] is None
    assert result["ebay_listing_count"] == 2
