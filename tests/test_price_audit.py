"""Releasing prices that a bug marked "yours".

Until 2.57.0 the Edit form resent both price fields on every save, and
`update_hat` reads a sent key as "a person typed this" — so editing a colorway
froze a scraped median as `manual` forever. 2.57.0 fixed the write path and
could not repair what was already written; nothing records which stamps came
from a person. Hence a report plus an explicit action, like the construction
audit, rather than a backfill that guesses.
"""

from __future__ import annotations

import pytest

from headroom.models.hat import Hat
from headroom.services import price_audit

pytestmark = pytest.mark.anyio


async def _hat(client, **overrides) -> int:
    resp = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hat_id = resp.json()["id"]
    if overrides:
        await client.put(f"/api/hats/{hat_id}", json=overrides)
    return hat_id


async def test_the_audit_finds_frozen_prices_and_flags_market_provenance(
    client, db_session
):
    typed = await _hat(client, resale_price=60.0)
    clean = await _hat(client)

    # A hat the marketplace priced, then something stamped manual — the shape
    # the pre-2.57.0 form produced.
    bug = await _hat(client, resale_price=52.5)
    row = await db_session.get(Hat, bug)
    row.resale_price_url = "https://melinrecap.com/l/abc"
    await db_session.commit()

    found = {r.hat_id: r for r in await price_audit.audit(db_session)}

    assert clean not in found, "a hat with no manual price is not frozen"
    assert typed in found and found[typed].was_market_priced is False
    assert found[bug].was_market_priced is True, (
        "marketplace provenance under a manual stamp is the bug's signature"
    )


async def test_release_defaults_to_a_dry_run_that_changes_nothing(client, db_session):
    hat_id = await _hat(client, resale_price=52.5)

    result = await price_audit.release(db_session)

    assert [r.hat_id for r in result] == [hat_id]
    db_session.expire_all()
    assert (await db_session.get(Hat, hat_id)).resale_price_scope == "manual", (
        "a bare release() call must not write — it names every frozen hat"
    )


async def test_releasing_clears_the_scope_but_keeps_the_number(client, db_session):
    hat_id = await _hat(client, resale_price=52.5, estimated_new_price=79.0)

    await price_audit.release(db_session, [hat_id], dry_run=False)

    db_session.expire_all()
    hat = await db_session.get(Hat, hat_id)
    assert hat.resale_price_scope is None, "still immune to the next analysis"
    assert hat.estimated_new_price_source is None
    assert hat.resale_price == 52.5, (
        "the number stays — a blank price is a worse answer than a stale one"
    )
    assert hat.estimated_new_price == 79.0


async def test_market_priced_only_narrows_to_the_likely_bug(client, db_session):
    typed = await _hat(client, resale_price=60.0)
    bug = await _hat(client, resale_price=52.5)
    row = await db_session.get(Hat, bug)
    row.resale_checked_at = row.created_at
    await db_session.commit()

    released = await price_audit.release(
        db_session, market_priced_only=True, dry_run=False
    )

    assert [r.hat_id for r in released] == [bug]
    db_session.expire_all()
    assert (await db_session.get(Hat, typed)).resale_price_scope == "manual", (
        "a hand-typed price with no marketplace history must be left alone"
    )


async def test_the_routes_are_admin_guarded_and_preview_by_default(client, anon_client):
    assert (await anon_client.get("/api/admin/prices/frozen")).status_code == 401
    assert (await anon_client.post("/api/admin/prices/release")).status_code == 401

    hat_id = await _hat(client, resale_price=52.5)
    body = (await client.post("/api/admin/prices/release")).json()

    assert body["dry_run"] is True
    assert body["released"] == 1
    assert (await client.get(f"/api/hats/{hat_id}")).json()["resale_price_scope"] == "manual"
