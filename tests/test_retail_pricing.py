"""melin retail prices are looked up, not guessed from a photo.

`estimated_new_price` used to come entirely from Claude Vision, steered by a
block of anchors in the prompt. A photo cannot show a price, so those anchors
were the real answer — and they said "HYDRO caps — $69 is the common price"
long after the band had moved to $79/$89. Every hat, and the retail-share
fallback in valuation, inherited that.
"""

from __future__ import annotations

import pytest

from headroom.services import retail_pricing

pytestmark = pytest.mark.anyio


async def test_the_prices_are_the_owners_numbers():
    """Cross-checked against 223 order lines: HydroLite was $99 x16."""
    assert retail_pricing.base_retail("a_game", "HYDRO") == 79.0
    assert retail_pricing.base_retail("coronado", "HYDROLite") == 99.0
    assert retail_pricing.base_retail("beanie", None) == 79.0
    assert retail_pricing.base_retail("aviator", None) == 99.0
    assert retail_pricing.CASE_RETAIL == 49.0


async def test_hydrolite_is_matched_before_hydro():
    """"hydro" is a substring of "hydrolite" — the wrong order prices every
    HydroLite as a plain Hydro, which is the $20 the two differ by."""
    assert retail_pricing.base_retail("a_game", "HYDROLite") == 99.0
    assert retail_pricing.base_retail("a_game", "hydrolite") == 99.0
    assert retail_pricing.base_retail("a_game", "A-Game HYDROLite") == 99.0


async def test_an_unknown_construction_returns_none_rather_than_a_guess():
    """None is a real answer: Thermal is $79/$89/$99 on caps and $139/$179 on
    Aviators, so any single number here would be invented."""
    assert retail_pricing.base_retail("odysea", "Thermal") is None
    assert retail_pricing.base_retail("a_game", None) is None
    assert retail_pricing.base_retail(None, None) is None


async def test_the_table_beats_a_low_estimate_but_not_a_high_one():
    """The base is what a PLAIN example costs. Above it is plausible — a collab
    or a straw Mill piece — and is exactly what the estimate is still for."""
    low, src = retail_pricing.resolve_retail(
        "a_game", "HYDRO", estimate=69.0, current=None, current_source=None
    )
    assert (low, src) == (79.0, retail_pricing.TABLE_SOURCE)

    high, src = retail_pricing.resolve_retail(
        "a_game", "HYDRO", estimate=180.0, current=None, current_source=None
    )
    assert (high, src) == (180.0, "Claude Vision")


async def test_a_manual_price_is_never_overwritten():
    """Somebody read a tag or an order confirmation. An unattended re-analysis
    replacing that is the worst kind of data loss — it looks like nothing
    happened."""
    price, src = retail_pricing.resolve_retail(
        "a_game", "HYDRO",
        estimate=180.0, current=89.0, current_source=retail_pricing.MANUAL_SOURCE,
    )
    assert (price, src) == (89.0, retail_pricing.MANUAL_SOURCE)


async def test_entering_a_retail_price_marks_it_manual_and_it_survives(client, db_session):
    """End to end: the PUT records the source, so the next analysis leaves it."""
    from headroom.models.hat import Hat

    resp = await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game",
        "construction": "HYDRO",
    })
    hat_id = resp.json()["id"]

    await client.put(f"/api/hats/{hat_id}", json={"estimated_new_price": 89.0})
    db_session.expire_all()
    row = await db_session.get(Hat, hat_id)
    assert row.estimated_new_price == 89.0
    assert row.estimated_new_price_source == retail_pricing.MANUAL_SOURCE

    # A later re-price must leave it alone.
    changed = await retail_pricing.backfill_retail_prices(db_session)
    db_session.expire_all()
    row = await db_session.get(Hat, hat_id)
    assert row.estimated_new_price == 89.0, f"backfill overwrote a manual price ({changed} changed)"


async def test_backfill_repairs_hats_priced_by_the_stale_anchors(client, db_session):
    """Fixing the code alone would leave the price depending on WHEN a hat was
    photographed."""
    from headroom.models.hat import Hat

    resp = await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game",
        "construction": "HYDROLite",
    })
    hat_id = resp.json()["id"]
    row = await db_session.get(Hat, hat_id)
    row.estimated_new_price = 69.0            # what the old anchor produced
    row.estimated_new_price_source = "Claude Vision"
    await db_session.commit()

    assert await retail_pricing.backfill_retail_prices(db_session) == 1
    db_session.expire_all()
    row = await db_session.get(Hat, hat_id)
    assert row.estimated_new_price == 99.0
    assert row.estimated_new_price_source == retail_pricing.TABLE_SOURCE


async def test_cases_publish_their_retail_price(client):
    body = (await client.post("/api/cases", json={"case_type": "archive"})).json()
    assert body["retail_price"] == 49.0
