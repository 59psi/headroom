"""Finding hats that are probably the same hat, entered twice.

Bulk import from a camera roll is how this happens — two photos of one hat
become two rows that both analyze plausibly. At forty hats you notice; at two
hundred you don't, and the collection reports more than you own, which then
flows into the valuation.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def _add(client, **over) -> dict:
    body = {"condition": "new", "size": "classic", "style": "trenches"}
    body.update(over)
    resp = await client.post("/api/hats", json=body)
    assert resp.status_code == 201, resp.text
    hat = resp.json()
    # Identity fields the picker can't set on create; the analyzer normally
    # fills these, so set them the way it would.
    edits = {k: over[k] for k in ("brand", "colorway") if k in over}
    if edits:
        resp = await client.put(f"/api/hats/{hat['id']}", json=edits)
        assert resp.status_code == 200, resp.text
        hat = resp.json()
    return hat


async def _groups(client) -> list[dict]:
    resp = await client.get("/api/search/duplicates")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_two_rows_for_one_hat_are_reported_together(client):
    a = await _add(client, model_name="Trenches Icon", brand="Melin", colorway="Black")
    b = await _add(client, model_name="Trenches Icon", brand="Melin", colorway="Black")

    groups = await _groups(client)

    assert len(groups) == 1
    assert groups[0]["confidence"] == "exact"
    assert {h["id"] for h in groups[0]["hats"]} == {a["id"], b["id"]}
    assert "Trenches Icon" in groups[0]["label"]


async def test_genuinely_different_hats_are_not_grouped(client):
    await _add(client, model_name="Trenches Icon", brand="Melin", colorway="Black")
    await _add(client, model_name="Trenches Icon", brand="Melin", colorway="Navy")
    await _add(client, model_name="A-Game Hydro", brand="Melin", colorway="Black")

    assert await _groups(client) == []


async def test_an_unanalyzed_twin_is_reported_as_likely(client):
    """The common bulk-import shape: one row analyzed, its twin not yet.

    Same model and size, colorway missing on one side — an exact match is
    impossible, and dropping it would hide the case this feature exists for.
    """
    await _add(client, model_name="Coronado", brand="Melin", colorway="Heather Ocean")
    await _add(client, model_name="Coronado", brand="Melin")

    groups = await _groups(client)

    assert len(groups) == 1
    assert groups[0]["confidence"] == "likely"
    assert len(groups[0]["hats"]) == 2


async def test_casing_and_spacing_do_not_hide_a_duplicate(client):
    """Identity fields are free text, so the comparison has to fold them."""
    await _add(client, model_name="Trenches Icon", brand="Melin", colorway="Black")
    await _add(client, model_name="trenches  icon", brand="MELIN", colorway="black")

    groups = await _groups(client)

    assert len(groups) == 1
    assert groups[0]["confidence"] == "exact"


async def test_hats_with_nothing_recorded_are_not_all_one_giant_group(client):
    """Without an identity floor, every un-analyzed hat matches every other on
    "same size, same style" and the report is one useless group."""
    for _ in range(4):
        await _add(client)

    assert await _groups(client) == []


async def test_a_disposed_hat_is_not_a_duplicate_of_the_one_you_kept(client):
    """One sold and one kept is a record of what happened, not a mistake."""
    a = await _add(client, model_name="Trenches Icon", brand="Melin", colorway="Black")
    b = await _add(client, model_name="Trenches Icon", brand="Melin", colorway="Black")

    assert len(await _groups(client)) == 1

    await client.post(f"/api/hats/{b['id']}/dispose", json={"via": "sold"})

    assert await _groups(client) == [], "a disposed hat was still counted"
    # The survivor is still an ordinary, active hat — nothing about it changed.
    assert (await client.get(f"/api/hats/{a['id']}")).json()["disposed_at"] is None


async def test_three_of_the_same_hat_come_back_as_one_group(client):
    """A triple is one group of three, not three pairs to reconcile by hand."""
    for _ in range(3):
        await _add(client, model_name="Trenches Icon", brand="Melin", colorway="Black")

    groups = await _groups(client)

    assert len(groups) == 1
    assert len(groups[0]["hats"]) == 3


async def test_size_distinguishes_two_real_hats(client):
    """The same cap in two sizes is two hats, deliberately owned."""
    await _add(client, model_name="Trenches Icon", brand="Melin", colorway="Black", size="classic")
    await _add(client, model_name="Trenches Icon", brand="Melin", colorway="Black", size="x_large")

    assert await _groups(client) == []
