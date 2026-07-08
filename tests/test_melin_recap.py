import pytest

from headroom.services.melin_recap import (
    build_resale_pointer,
    is_melin,
    melin_recap_link,
)

# The autouse setup_db fixture in conftest is async, so every test in the
# suite needs the anyio plugin even when the test body itself is synchronous.
pytestmark = pytest.mark.anyio


async def test_is_melin_matches_case_insensitive():
    assert is_melin("Melin") is True
    assert is_melin("MELIN BRAND") is True
    assert is_melin("New Era") is False
    assert is_melin(None) is False
    assert is_melin("") is False


async def test_link_for_known_styles_uses_filter_param():
    url = melin_recap_link("a_game")
    assert "pub_category=aGame" in url
    assert "filter-change" in url


async def test_link_falls_back_for_unknown_style():
    url = melin_recap_link("beanie")
    assert url == "https://www.melinrecap.com/"


async def test_build_pointer_only_for_melin():
    assert build_resale_pointer("Melin", "odysea") == {
        "resale_price": None,
        "resale_price_source": "Melin Recap",
        "resale_price_url": "https://www.melinrecap.com/?mode=filter-change&pub_category=odysea",
    }
    assert build_resale_pointer("New Era", "fitted") is None
    assert build_resale_pointer(None, "a_game") is None


# ---------------------- live marketplace stats ------------------------ #


def _listing(title: str, cents: int | None) -> dict:
    attrs: dict = {"title": title}
    if cents is not None:
        attrs["price"] = {"amount": cents, "currency": "USD"}
    return {"id": "x", "type": "listing", "attributes": attrs}


def _stub_query(monkeypatch, listings):
    captured: dict = {}

    async def _fake_query(params):
        captured.update(params)
        return listings

    monkeypatch.setattr(
        "headroom.services.melin_recap._query_listings", _fake_query
    )
    return captured


async def test_stats_median_over_category(monkeypatch):
    from headroom.services.melin_recap import fetch_resale_stats

    params = _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 8900),
        _listing("A-Game Scout - Grey", 5500),
        _listing("A-Game Classic - Navy", 7000),
        _listing("No price listing", None),
    ])
    stats = await fetch_resale_stats("a_game", None)
    assert params["pub_category"] == "aGame"
    assert stats == {"median": 70.0, "count": 3, "sample": "category"}


async def test_stats_narrows_to_model_when_sample_big_enough(monkeypatch):
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 8000),
        _listing("A-Game Hydro - Grey", 9000),
        _listing("a-game hydro - Navy", 10000),
        _listing("A-Game Scout - Grey", 1000),
    ])
    stats = await fetch_resale_stats("a_game", "A-Game Hydro")
    assert stats == {"median": 90.0, "count": 3, "sample": "model"}


async def test_stats_widens_when_model_sample_too_small(monkeypatch):
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 8000),
        _listing("A-Game Scout - Grey", 2000),
        _listing("A-Game Classic - Navy", 5000),
    ])
    stats = await fetch_resale_stats("a_game", "A-Game Hydro")
    assert stats["sample"] == "category"
    assert stats["count"] == 3
    assert stats["median"] == 50.0


async def test_stats_none_without_style_or_model(monkeypatch):
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [])
    assert await fetch_resale_stats(None, None) is None


async def test_refresh_melin_resale_persists_median(monkeypatch):
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import refresh_melin_resale

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 8000),
        _listing("A-Game Hydro - Grey", 9000),
        _listing("A-Game Hydro - Navy", 10000),
    ])
    hat = Hat(condition="new", size="classic", style="a_game", brand="Melin",
              model_name="A-Game Hydro")
    await refresh_melin_resale(hat)
    assert hat.resale_price == 90.0
    assert "median of 3 live model listings" in hat.resale_price_source
    assert hat.resale_checked_at is not None


async def test_refresh_degrades_silently_when_api_unreachable():
    """Autouse conftest stub raises MelinRecapError — old link-only behavior."""
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import refresh_melin_resale

    hat = Hat(condition="new", size="classic", style="a_game", brand="Melin")
    await refresh_melin_resale(hat)
    assert hat.resale_price is None


async def test_refresh_skips_non_melin():
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import refresh_melin_resale

    hat = Hat(condition="new", size="classic", style="a_game", brand="New Era")
    await refresh_melin_resale(hat)
    assert hat.resale_price is None
    assert hat.resale_checked_at is None
