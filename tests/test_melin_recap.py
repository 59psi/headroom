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


def _listing(
    title: str, cents: int | None, condition: str = "new_with_tags", size: str = "C"
) -> dict:
    """One marketplace listing. `condition` and `size` live in publicData and
    are what make a median comparable — see `fetch_resale_stats`."""
    attrs: dict = {"title": title, "publicData": {"condition": condition, "size": size}}
    if cents is not None:
        attrs["price"] = {"amount": cents, "currency": "USD"}
    return {"id": "x", "type": "listing", "attributes": attrs}


def _stub_query(monkeypatch, listings):
    captured: dict = {}

    async def _fake_query(params):
        captured.update(params)
        return listings

    monkeypatch.setattr(
        "headroom.services.melin_recap.query_listings", _fake_query
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
    # Field-wise, not whole-dict: the payload gains keys as the matcher learns
    # to scope, and an == here fails on additions that break nothing.
    assert stats["median"] == 70.0
    assert stats["count"] == 3
    assert stats["sample"] == "category"


async def test_stats_narrows_to_model_when_sample_big_enough(monkeypatch):
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 8000),
        _listing("A-Game Hydro - Grey", 9000),
        _listing("a-game hydro - Navy", 10000),
        _listing("A-Game Scout - Grey", 1000),
    ])
    stats = await fetch_resale_stats("a_game", "A-Game Hydro")
    assert stats["median"] == 90.0
    assert stats["count"] == 3
    assert stats["sample"] == "model"


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


# ---------------- scope: what the price is a price OF ----------------- #
#
# Valuation branches on `resale_price_scope` because the three cases are
# different measurements, not degrees of confidence in one: a category median
# is the going rate for a whole style, and treating it as this hat's value gave
# every hat in a category the same number.


async def test_scope_records_model_when_listings_match_the_model(monkeypatch):
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
    assert hat.resale_price_scope == "model"


async def test_scope_records_category_when_the_model_sample_is_too_small(monkeypatch):
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import refresh_melin_resale

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 8000),
        _listing("A-Game Scout - Grey", 2000),
        _listing("A-Game Classic - Navy", 5000),
    ])
    hat = Hat(condition="new", size="classic", style="a_game", brand="Melin",
              model_name="A-Game Hydro")
    await refresh_melin_resale(hat)
    assert hat.resale_price_scope == "category"
    assert "live category listings" in hat.resale_price_source


async def test_manual_resale_price_survives_a_refresh(monkeypatch):
    """A number a person typed outranks a scraped median.

    Reanalysis runs unattended from the bulk queue, so anything it overwrites
    is gone with no prompt and nothing to restore it from.
    """
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import refresh_melin_resale

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 8000),
        _listing("A-Game Hydro - Grey", 9000),
        _listing("A-Game Hydro - Navy", 10000),
    ])
    hat = Hat(condition="new", size="classic", style="a_game", brand="Melin",
              model_name="A-Game Hydro", resale_price=250.0,
              resale_price_scope="manual")
    await refresh_melin_resale(hat)
    assert hat.resale_price == 250.0
    assert hat.resale_price_scope == "manual"


async def test_manual_resale_price_survives_the_pointer_pass():
    """`_apply_resale_pointer` assigns a None price by construction.

    It ran on every analysis of a Melin hat and relied on the live refresh
    putting a number back afterwards. When the marketplace API is unreachable
    it doesn't — so a hand-entered price vanished on any reanalysis that
    happened to coincide with an outage.
    """
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import _apply_resale_pointer

    hat = Hat(condition="new", size="classic", style="a_game", brand="Melin",
              resale_price=250.0, resale_price_scope="manual")
    _apply_resale_pointer(hat)
    assert hat.resale_price == 250.0
    # The deep link is still refreshed — it is safe to replace and useful.
    assert hat.resale_price_url


async def test_editing_resale_price_marks_it_manual(client):
    """The PUT path is the only place a person's own price enters."""
    created = await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game",
    })
    hat_id = created.json()["id"]

    resp = await client.put(f"/api/hats/{hat_id}", json={"resale_price": 175.0})
    assert resp.status_code == 200
    assert resp.json()["resale_price"] == 175.0
    assert resp.json()["resale_price_scope"] == "manual"

    # Clearing it must drop the marker too, or the hat keeps claiming a manual
    # price it no longer has and blocks every future refresh.
    cleared = await client.put(f"/api/hats/{hat_id}", json={"resale_price": None})
    assert cleared.json()["resale_price_scope"] is None


# ------------- condition- and size-matched comparables (v2.21) --------- #
#
# The listed price IS the sale price here: fixed-price marketplace, automatic
# drops, no negotiation. So comparability comes from FILTERING, not from
# discounting. This used to median across every condition and leave the caller
# to multiply by a guessed factor — guesses that measured wrong against 706
# live listings (new-without-tags is 0.95 of new-with-tags, not 0.92; worn is
# 0.82, not 0.78) and were never needed with the real number in the feed.


async def test_median_is_scoped_to_the_hats_condition(monkeypatch):
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 10000, condition="new_with_tags"),
        _listing("A-Game Hydro - Grey", 10000, condition="new_with_tags"),
        _listing("A-Game Hydro - Navy", 10000, condition="new_with_tags"),
        _listing("A-Game Hydro - Bone", 5000, condition="excellent"),
        _listing("A-Game Hydro - Tan", 5000, condition="excellent"),
        _listing("A-Game Hydro - Sand", 5000, condition="excellent"),
    ])
    worn = await fetch_resale_stats("a_game", "A-Game Hydro", condition="worn")
    assert worn["median"] == 50.0, "a worn hat is priced against worn listings"
    assert worn["condition_matched"] is True

    tagged = await fetch_resale_stats("a_game", "A-Game Hydro", condition="new_with_tags")
    assert tagged["median"] == 100.0
    # Before this, both got one median across everything — 75 apiece.


async def test_size_narrows_further_when_the_sample_allows(monkeypatch):
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - A", 12000, size="XL"),
        _listing("A-Game Hydro - B", 12000, size="XL"),
        _listing("A-Game Hydro - C", 12000, size="XL"),
        _listing("A-Game Hydro - D", 6000, size="C"),
        _listing("A-Game Hydro - E", 6000, size="C"),
        _listing("A-Game Hydro - F", 6000, size="C"),
    ])
    stats = await fetch_resale_stats(
        "a_game", "A-Game Hydro", condition="new_with_tags", size="x_large"
    )
    assert stats["median"] == 120.0
    assert stats["size_matched"] is True


async def test_it_widens_rather_than_answering_from_one_listing(monkeypatch):
    """Falling back beats answering from a sample too small to mean anything."""
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - A", 9000, condition="new_with_tags", size="XL"),
        _listing("A-Game Hydro - B", 6000, condition="new_with_tags", size="C"),
        _listing("A-Game Hydro - C", 6000, condition="new_with_tags", size="C"),
        _listing("A-Game Hydro - D", 6000, condition="new_with_tags", size="C"),
    ])
    # Only ONE x_large — too few, so size is dropped and condition is kept.
    stats = await fetch_resale_stats(
        "a_game", "A-Game Hydro", condition="new_with_tags", size="x_large"
    )
    assert stats["size_matched"] is False
    assert stats["condition_matched"] is True
    assert stats["count"] == 4


async def test_an_unknown_marketplace_condition_counts_as_worn(monkeypatch):
    """An unrecognised condition is certainly not new. Guessing "new" would
    quietly inflate every valuation that used it."""
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - A", 4000, condition="beat_to_hell"),
        _listing("A-Game Hydro - B", 4000, condition="good"),
        _listing("A-Game Hydro - C", 4000, condition="fair"),
    ])
    stats = await fetch_resale_stats("a_game", "A-Game Hydro", condition="worn")
    assert stats["condition_matched"] is True
    assert stats["median"] == 40.0


async def test_no_condition_given_still_works(monkeypatch):
    """Back-compat: a caller that states no condition gets the old behaviour."""
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - A", 8000),
        _listing("A-Game Hydro - B", 9000),
        _listing("A-Game Hydro - C", 10000),
    ])
    stats = await fetch_resale_stats("a_game", "A-Game Hydro")
    assert stats["median"] == 90.0
    assert stats["condition_matched"] is False


async def test_the_source_label_names_what_was_matched(monkeypatch):
    """"median of 8 live listings" gives no way to tell a figure drawn from
    this exact hat in this condition from one drawn from the whole category."""
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import refresh_melin_resale

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - A", 8000, condition="excellent", size="C"),
        _listing("A-Game Hydro - B", 9000, condition="excellent", size="C"),
        _listing("A-Game Hydro - C", 10000, condition="excellent", size="C"),
    ])
    hat = Hat(condition="worn", size="classic", style="a_game", brand="Melin",
              model_name="A-Game Hydro")
    await refresh_melin_resale(hat)
    assert hat.resale_price == 90.0
    assert "classic" in hat.resale_price_source
    assert "worn" in hat.resale_price_source
    assert "model listings" in hat.resale_price_source
