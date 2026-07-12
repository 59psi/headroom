"""Colorway catalog (melinrecap harvest) + purchase-history import/matching."""

from __future__ import annotations

import pytest

from headroom.services.catalog_service import parse_listing_title

pytestmark = pytest.mark.anyio


async def test_parse_listing_title_variants():
    assert parse_listing_title("A-Game Hydro - Heather Grey") == ("A-Game Hydro", "Heather Grey")
    assert parse_listing_title("Coronado Brick Hydro - Heather Ocean / Heather Charcoal") == (
        "Coronado Brick Hydro", "Heather Ocean / Heather Charcoal",
    )
    # No separator → model only
    assert parse_listing_title("Odysea Journey") == ("Odysea Journey", None)
    # Hyphen inside the model name only splits on " - " (spaced)
    assert parse_listing_title("A-Game Scout")[0] == "A-Game Scout"


def _pages(monkeypatch, pages_by_category):
    """Stub _query_listings: serve canned title pages per category."""
    async def _fake(params):
        cat = params["pub_category"]
        page = params.get("page", 1)
        titles = pages_by_category.get(cat, [])
        per = params["per_page"]
        chunk = titles[(page - 1) * per : page * per]
        return [{"attributes": {"title": t}} for t in chunk]

    monkeypatch.setattr("headroom.services.catalog_service._query_listings", _fake)


async def test_harvest_upserts_and_counts(client, db_session, monkeypatch):
    from headroom.services.catalog_service import harvest_catalog

    _pages(monkeypatch, {
        "aGame": ["A-Game Hydro - Red", "A-Game Hydro - Red", "A-Game Scout - Grey"],
        "odysea": ["Odysea - Moss"],
    })
    result = await harvest_catalog(db_session)
    assert result["new_entries"] == 3          # dupe title upserted, not doubled
    assert result["catalog_total"] == 3

    # Second harvest adds nothing new but bumps counts
    result = await harvest_catalog(db_session)
    assert result["new_entries"] == 0
    assert result["catalog_total"] == 3


async def test_colorway_autocomplete_endpoint(client, db_session, monkeypatch):
    from headroom.services.catalog_service import harvest_catalog

    _pages(monkeypatch, {
        "aGame": ["A-Game Hydro - Heather Grey", "A-Game Hydro - Red", "A-Game Scout - Grey"],
    })
    await harvest_catalog(db_session)

    models = (await client.get("/api/meta/colorways")).json()
    assert {"value": "A-Game Hydro"} in models

    cws = (await client.get("/api/meta/colorways", params={"model": "a-game hydro"})).json()
    values = [c["value"] for c in cws]
    assert "Heather Grey" in values and "Red" in values and "Grey" not in values


async def test_purchase_import_dedupe_and_match(client, db_session):
    # A hat Claude identified but with no colorway/cost basis yet
    hat = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hat_id = hat.json()["id"]
    from headroom.models.hat import Hat

    row = await db_session.get(Hat, hat_id)
    row.model_name = "A-Game Hydro"
    await db_session.commit()

    items = [
        {"item_title": "A-Game Hydro - Heather Grey", "order_ref": "M123",
         "order_date": "2024-06-01", "price": 69.0},
        {"item_title": "A-Game Hydro - Heather Grey", "order_ref": "M123",
         "order_date": "2024-06-01", "price": 69.0},  # dupe
        {"item_title": "Odysea - Moss", "order_ref": "M124", "price": 79.0},
    ]
    resp = await client.post("/api/admin/purchases/import", json={"items": items})
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 2
    assert body["skipped"] == 1
    assert body["matched"] == 1     # the A-Game Hydro linked to our hat
    assert body["unmatched"] == 1   # no Odysea hat exists

    updated = (await client.get(f"/api/hats/{hat_id}")).json()
    assert updated["colorway"] == "Heather Grey"
    assert updated["purchase_price"] == 69.0
    assert updated["purchased_at"] is not None

    purchases = (await client.get("/api/admin/purchases")).json()
    linked = [p for p in purchases if p["hat_id"] == hat_id]
    assert len(linked) == 1


async def test_match_respects_colorway_disagreement(client, db_session):
    from headroom.models.hat import Hat

    hat = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hat_id = hat.json()["id"]
    row = await db_session.get(Hat, hat_id)
    row.model_name = "A-Game Hydro"
    row.colorway = "Red"  # user already set it
    await db_session.commit()

    resp = await client.post(
        "/api/admin/purchases/import",
        json={"items": [{"item_title": "A-Game Hydro - Heather Grey", "price": 69.0}]},
    )
    assert resp.json()["matched"] == 0  # colorways disagree → no link

    updated = (await client.get(f"/api/hats/{hat_id}")).json()
    assert updated["colorway"] == "Red"
    assert updated["purchase_price"] is None
