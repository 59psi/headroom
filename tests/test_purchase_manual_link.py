"""Linking a purchase to a hat by hand, and receipt colorways wired through.

The matcher links what its rules can tell apart. On the owner's real shelf
that left 95 of 294 purchase units unmatched: 78 were travel cases, and most
of the 17 hat lines missed on spelling — receipts say "Odyssey" where every
hat says "Odysea", and "The Shore Hydro" where the hat says "Shore Hydro".
The rest needed a person: fifteen `Trenches Hydro` hats with nothing on
record to tell them apart. These cover the matcher's spelling fixes, the
accessory flag, the ranked pick lists, the hand-made link (and its undo),
and the receipt's colorway reaching the picker and the analyzer's validator.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy import update as sa_update

from headroom.models import Hat, Purchase
from headroom.services import catalog_service

pytestmark = pytest.mark.anyio


def _hat(model, **extra):
    return {"condition": "new", "size": "classic", "style": "odysea", "model_name": model, **extra}


def _line(title, ref, **extra):
    return {"item_title": title, "order_ref": ref, "price": 79.0, "quantity": 1,
            "size": "Classic", "order_date": "2025-03-05", **extra}


async def _import(client, *lines):
    resp = await client.post("/api/admin/purchases/import", json={"items": list(lines)})
    assert resp.status_code == 200, resp.text
    return {p["order_ref"]: p for p in (await client.get("/api/admin/purchases")).json()}


async def _new_hat(client, model, **extra):
    resp = await client.post("/api/hats", json=_hat(model, **extra))
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _set_colorway(db_session, hat_id, colorway):
    await db_session.execute(sa_update(Hat).where(Hat.id == hat_id).values(colorway=colorway))
    await db_session.commit()


# ---- the matcher's spelling fixes ------------------------------------------ #


async def test_a_receipt_spelling_odyssey_matches_an_odysea_hat(client):
    hat_id = await _new_hat(client, "Odysea Hydro")
    rows = await _import(client, _line("Odyssey Aloha Hydro - Black", "R1"))
    assert rows["R1"]["hat_id"] == hat_id, "the Odyssey spelling kept the receipt off its hat"


async def test_a_leading_the_is_ignored_on_either_side(client):
    """A receipt with MORE words already reaches a hat by containment, so
    the article only decides anything the other way round: a hat recorded
    as "The Shore Hydro" against a receipt that leaves it off."""
    hat_id = await _new_hat(client, "The Shore Hydro")
    rows = await _import(client, _line("Shore Hydro - Ink Camo", "R1"))
    assert rows["R1"]["hat_id"] == hat_id


async def test_the_same_line_with_and_without_the_is_an_exact_model_match():
    assert catalog_service._model_tier("Shore Hydro", "The Shore Hydro") == catalog_service.MODEL_EXACT


# ---- accessories ------------------------------------------------------------ #


async def test_travel_cases_are_flagged_as_accessories(client):
    rows = await _import(
        client,
        _line("3 Hat Travel Case - Black", "C1", size=None, price=49.0),
        _line("Odysea Hydro - Navy", "H1"),
    )
    assert rows["C1"]["accessory"] is True
    assert rows["H1"]["accessory"] is False


# ---- pick lists ------------------------------------------------------------- #


async def test_the_hat_list_leads_with_fits_and_still_offers_the_rest(client):
    rows = await _import(client, _line("Trenches Icon Hydro - Black Camo", "R1"))
    other = await _new_hat(client, "Eagle Denim")  # created first: order must come from the fit
    fits = await _new_hat(client, "Trenches Hydro")

    resp = await client.get(f"/api/admin/purchases/{rows['R1']['id']}/hats")
    assert resp.status_code == 200, resp.text
    options = resp.json()["options"]
    ids = [o["hat_id"] for o in options]
    assert ids[0] == fits and options[0]["fits"] is True
    assert other in ids, "a hat the rules exclude must still be offered — that is why a person picks"
    assert next(o for o in options if o["hat_id"] == other)["fits"] is False


async def test_the_hat_list_flags_a_hat_that_already_holds_a_purchase(client):
    taken = await _new_hat(client, "Odysea Hydro")
    rows = await _import(client, _line("Odysea Hydro - Navy", "R1"), _line("Odysea Hydro - Navy", "R2"))
    holder = next(p for p in rows.values() if p["hat_id"] == taken)
    free = next(p for p in rows.values() if p["hat_id"] is None)

    options = (await client.get(f"/api/admin/purchases/{free['id']}/hats")).json()["options"]
    assert next(o for o in options if o["hat_id"] == taken)["linked_purchase_id"] == holder["id"]


async def test_the_purchase_list_for_a_hat_skips_accessories(client):
    hat_id = await _new_hat(client, "Odysea Hydro")
    await _import(client, _line("3 Hat Travel Case - Black", "C1", size=None, price=49.0))
    resp = await client.get(f"/api/admin/purchases/for-hat/{hat_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["options"] == []


async def test_the_purchase_list_for_a_hat_shows_its_link_and_flags_others(client):
    a = await _new_hat(client, "Odysea Hydro")
    rows = await _import(client, _line("Odysea Hydro - Navy", "R1"))
    b = await _new_hat(client, "Odysea Hydro")

    for_b = (await client.get(f"/api/admin/purchases/for-hat/{b}")).json()
    assert for_b["linked"] == []
    elsewhere = next(o for o in for_b["options"] if o["id"] == rows["R1"]["id"])
    assert elsewhere["linked_hat_id"] == a, "a purchase on another hat is offered, flagged, to move"
    for_a = (await client.get(f"/api/admin/purchases/for-hat/{a}")).json()
    assert [p["id"] for p in for_a["linked"]] == [rows["R1"]["id"]]


# ---- linking ----------------------------------------------------------------- #


async def test_linking_fills_the_hats_empty_fields_and_unlink_undoes_it(client):
    rows = await _import(client, _line("Trenches Icon Hydro - Black Camo", "R1", price=89.0))
    hat_id = await _new_hat(client, "Eagle Denim")  # nothing the matcher would pair
    pid = rows["R1"]["id"]

    resp = await client.post(f"/api/admin/purchases/{pid}/link", json={"hat_id": hat_id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["wrote"] == ["colorway", "purchase_price", "purchased_at"]
    hat = (await client.get(f"/api/hats/{hat_id}")).json()
    assert (hat["purchase_price"], hat["colorway"]) == (89.0, "Black Camo")

    assert (await client.post(f"/api/admin/purchases/{pid}/unmatch")).status_code == 200
    hat = (await client.get(f"/api/hats/{hat_id}")).json()
    assert (hat["purchase_price"], hat["colorway"]) == (None, None)


async def test_linking_never_overwrites_what_the_hat_already_says(client, db_session):
    rows = await _import(client, _line("Odysea Hydro - Navy", "R1", price=79.0))
    hat_id = await _new_hat(client, "Eagle Denim", purchase_price=60.0)
    await _set_colorway(db_session, hat_id, "Bone")

    resp = await client.post(f"/api/admin/purchases/{rows['R1']['id']}/link", json={"hat_id": hat_id})
    assert resp.json()["wrote"] == ["purchased_at"]
    hat = (await client.get(f"/api/hats/{hat_id}")).json()
    assert (hat["purchase_price"], hat["colorway"]) == (60.0, "Bone")


async def test_the_receipt_colorway_replaces_a_wrong_one_only_when_asked(client, db_session):
    rows = await _import(client, _line("Eagle Mill Union - Hickory Denim", "R1", price=200.0))
    hat_id = await _new_hat(client, "Eagle Denim")
    await _set_colorway(db_session, hat_id, "Navy Denium")
    pid = rows["R1"]["id"]

    resp = await client.post(
        f"/api/admin/purchases/{pid}/link", json={"hat_id": hat_id, "receipt_colorway": True}
    )
    assert resp.status_code == 200, resp.text
    assert "colorway" in resp.json()["wrote"]
    assert (await client.get(f"/api/hats/{hat_id}")).json()["colorway"] == "Hickory Denim"

    await client.post(f"/api/admin/purchases/{pid}/unmatch")
    assert (await client.get(f"/api/hats/{hat_id}")).json()["colorway"] == "Navy Denium", (
        "unlinking must put back the colorway the receipt replaced, not blank it"
    )


async def test_a_hat_holding_a_purchase_is_a_conflict_unless_replaced(client):
    hat_id = await _new_hat(client, "Odysea Hydro")
    rows = await _import(client, _line("Odysea Hydro - Navy", "R1", price=79.0),
                         _line("Odysea Hydro - Navy", "R2", price=99.0))
    holder = next(p for p in rows.values() if p["hat_id"] == hat_id)
    other = next(p for p in rows.values() if p["hat_id"] is None)

    refused = await client.post(f"/api/admin/purchases/{other['id']}/link", json={"hat_id": hat_id})
    assert refused.status_code == 409
    assert "already linked" in refused.json()["detail"]

    resp = await client.post(
        f"/api/admin/purchases/{other['id']}/link", json={"hat_id": hat_id, "replace": True}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["replaced_purchase_id"] == holder["id"]
    after = {p["id"]: p for p in (await client.get("/api/admin/purchases")).json()}
    assert after[holder["id"]]["hat_id"] is None
    assert after[other["id"]]["hat_id"] == hat_id
    assert (await client.get(f"/api/hats/{hat_id}")).json()["purchase_price"] == other["price"], (
        "the replaced purchase's price must be reverted and the new one written"
    )


async def test_linking_a_purchase_from_one_hat_to_another_moves_it(client):
    a = await _new_hat(client, "Odysea Hydro")
    rows = await _import(client, _line("Odysea Hydro - Navy", "R1", price=79.0))
    b = await _new_hat(client, "Odysea Hydro")
    pid = rows["R1"]["id"]

    resp = await client.post(f"/api/admin/purchases/{pid}/link", json={"hat_id": b})
    assert resp.status_code == 200, resp.text
    assert resp.json()["moved_from_hat_id"] == a
    assert (await client.get(f"/api/hats/{a}")).json()["purchase_price"] is None
    assert (await client.get(f"/api/hats/{b}")).json()["purchase_price"] == 79.0


async def test_linking_logs_who_made_the_link(client, db_session):
    from headroom.models import ActivityLog

    rows = await _import(client, _line("Odysea Hydro - Navy", "R1"))
    hat_id = await _new_hat(client, "Eagle Denim")
    await client.post(f"/api/admin/purchases/{rows['R1']['id']}/link", json={"hat_id": hat_id})
    kinds = (await db_session.execute(select(ActivityLog.kind))).scalars().all()
    assert "purchase.linked" in kinds


async def test_linking_unknown_rows_is_not_found(client):
    hat_id = await _new_hat(client, "Odysea Hydro")
    assert (await client.post("/api/admin/purchases/999/link", json={"hat_id": hat_id})).status_code == 404
    rows = await _import(client, _line("Odysea Hydro - Navy", "R1"))
    pid = next(iter(rows.values()))["id"]
    assert (await client.post(f"/api/admin/purchases/{pid}/link", json={"hat_id": 999})).status_code == 404
    assert (await client.get("/api/admin/purchases/999/hats")).status_code == 404
    assert (await client.get("/api/admin/purchases/for-hat/999")).status_code == 404


# ---- receipt colorways, wired through -------------------------------------- #


async def test_the_colorway_picker_offers_what_was_bought_first(client, db_session):
    # The case names the line it fits — the shape where only the accessory
    # rule, not the model rule, keeps its colorway out.
    await _import(client, _line("Odyssey Neon Hydro - Neon Orange", "R1"),
                  _line("Odysea Hydro Travel Case - Black", "C1", size=None, price=49.0))
    options = await catalog_service.catalog_options(db_session, model="Odysea Hydro")
    values = [o["value"] for o in options]
    assert values and values[0] == "Neon Orange", "a colorway on the owner's receipt must be offered"
    assert "Black" not in values, "a travel case's colorway is not a hat's"


async def test_a_colorway_on_a_receipt_counts_as_a_real_product(client, db_session):
    await _import(client, _line("Eagle Mill Union - Hickory Denim", "R1"))
    assert await catalog_service.is_real_product(db_session, "Eagle Mill Union", "Hickory Denim")
    assert not await catalog_service.is_real_product(db_session, "Eagle Mill Union", "Hickory")
    count = len((await db_session.execute(select(Purchase))).scalars().all())
    assert count == 1
