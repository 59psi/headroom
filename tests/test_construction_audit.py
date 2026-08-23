"""Undoing constructions that analysis guessed.

Nothing in the database records whether a construction came from a person or
from a photo, so this cannot be a startup backfill that decides for the owner.
It is a report plus an explicit, previewable action — and because it removes
data that cannot be recomputed, the destructive form has to be asked for.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def _hat(client, **fields):
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game", **fields},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _set_price(db_session, hat_id, price, source):
    """Put a hat in the state analysis would have left it in.

    Written through the test session rather than the API: `estimated_new_price`
    arriving over a PUT is marked `Manual` by design, which is the very thing
    several of these tests need to distinguish from a table-derived price.
    """
    from sqlalchemy import select

    from headroom.models.hat import Hat

    hat = (await db_session.execute(select(Hat).where(Hat.id == hat_id))).scalar_one()
    hat.estimated_new_price = price
    hat.estimated_new_price_source = source
    await db_session.commit()


async def test_audit_reports_what_is_on_record(client):
    await _hat(client, construction="HYDROLite")
    await _hat(client, construction="HYDROLite")
    await _hat(client, construction="Thermal")

    rows = (await client.get("/api/admin/constructions/audit")).json()

    by_value = {r["construction"]: r for r in rows}
    assert by_value["HYDROLite"]["hat_count"] == 2
    assert by_value["Thermal"]["hat_count"] == 1
    # Most common first, so the thing worth reviewing is at the top.
    assert rows[0]["construction"] == "HYDROLite"


async def test_audit_counts_prices_derived_from_the_construction(client, db_session):
    """The number that says how much a wrong guess is worth undoing."""
    hat_id = await _hat(client, construction="HYDROLite")
    await _set_price(db_session, hat_id, 99.0, "melin retail")

    rows = (await client.get("/api/admin/constructions/audit")).json()

    row = next(r for r in rows if r["construction"] == "HYDROLite")
    assert row["priced_from_table"] == 1


async def test_clear_defaults_to_a_dry_run(client):
    """It removes data that cannot be recomputed, so it must be asked for."""
    hat_id = await _hat(client, construction="HYDROLite")

    body = (await client.post("/api/admin/constructions/clear?value=HYDROLite")).json()

    assert body["dry_run"] is True
    assert body["hats_cleared"] == 1
    # Nothing actually changed.
    assert (await client.get(f"/api/hats/{hat_id}")).json()["construction"] == "HYDROLite"


async def test_clearing_removes_the_construction_and_its_flags(client):
    hat_id = await _hat(client, construction="HYDROLite")

    body = (await client.post(
        "/api/admin/constructions/clear?value=HYDROLite&dry_run=false"
    )).json()

    assert body["hats_cleared"] == 1
    hat = (await client.get(f"/api/hats/{hat_id}")).json()
    assert hat["construction"] is None
    assert hat["hydrolite"] is False, "derived flag outlived the value it indexes"
    assert hat["hydro"] is False


async def test_clearing_also_strips_the_word_from_the_model_name(client):
    """melin names read "<line> <construction>", so the guess lives there too —
    in the field a person actually reads and quotes."""
    hat_id = await _hat(client, construction="HYDROLite", model_name="A-Game HYDROLite")

    body = (await client.post(
        "/api/admin/constructions/clear?value=HYDROLite&dry_run=false"
    )).json()

    assert body["model_names_corrected"] == 1
    assert (await client.get(f"/api/hats/{hat_id}")).json()["model_name"] == "A-Game"


async def test_clearing_drops_a_price_that_was_derived_from_the_construction(client, db_session):
    """HYDROLite prices at $99 and HYDRO at $79, so a guessed HYDROLite carried
    a $20 premium. Leaving the number while removing its reason would be a
    price with no derivation, indistinguishable from one somebody checked."""
    hat_id = await _hat(client, construction="HYDROLite")
    await _set_price(db_session, hat_id, 99.0, "melin retail")

    body = (await client.post(
        "/api/admin/constructions/clear?value=HYDROLite&dry_run=false"
    )).json()

    assert body["prices_cleared"] == 1
    hat = (await client.get(f"/api/hats/{hat_id}")).json()
    assert hat["estimated_new_price"] is None
    assert hat["estimated_new_price_source"] is None


async def test_a_manually_entered_price_survives(client, db_session):
    """Same protection a Manual price has everywhere else: somebody read a tag
    or an order confirmation, and nothing derived may overwrite that."""
    hat_id = await _hat(client, construction="HYDROLite")
    await _set_price(db_session, hat_id, 120.0, "Manual")

    body = (await client.post(
        "/api/admin/constructions/clear?value=HYDROLite&dry_run=false"
    )).json()

    assert body["manual_prices_kept"] == 1
    assert body["prices_cleared"] == 0
    assert (await client.get(f"/api/hats/{hat_id}")).json()["estimated_new_price"] == 120.0


async def test_clearing_leaves_other_constructions_alone(client):
    thermal = await _hat(client, construction="Thermal")
    lite = await _hat(client, construction="HYDROLite")

    await client.post("/api/admin/constructions/clear?value=HYDROLite&dry_run=false")

    assert (await client.get(f"/api/hats/{thermal}")).json()["construction"] == "Thermal"
    assert (await client.get(f"/api/hats/{lite}")).json()["construction"] is None


async def test_matching_ignores_casing(client):
    """The stored spelling is whatever was written at the time."""
    hat_id = await _hat(client, construction="HYDROLite")

    body = (await client.post(
        "/api/admin/constructions/clear?value=hydrolite&dry_run=false"
    )).json()

    assert body["hats_cleared"] == 1
    assert (await client.get(f"/api/hats/{hat_id}")).json()["construction"] is None


async def test_disposed_hats_are_left_out(client):
    hat_id = await _hat(client, construction="HYDROLite")
    await client.post(f"/api/hats/{hat_id}/dispose", json={"via": "sold"})

    body = (await client.post(
        "/api/admin/constructions/clear?value=HYDROLite&dry_run=false"
    )).json()

    assert body["hats_cleared"] == 0


async def test_the_endpoints_are_auth_gated(anon_client):
    assert (await anon_client.get("/api/admin/constructions/audit")).status_code == 401
    assert (
        await anon_client.post("/api/admin/constructions/clear?value=HYDROLite")
    ).status_code == 401
