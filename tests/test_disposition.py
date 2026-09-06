"""Tests for hat disposition (sold/gifted/lost) tracking."""

import pytest
from headroom.services import capacity

pytestmark = pytest.mark.anyio


async def _make_hat(client, **overrides):
    payload = {"condition": "new", "size": "classic", "style": "a_game"}
    payload.update(overrides)
    resp = await client.post("/api/hats", json=payload)
    return resp.json()


async def test_dispose_sets_fields(client):
    hat = await _make_hat(client)
    resp = await client.post(
        f"/api/hats/{hat['id']}/dispose",
        json={"via": "sold", "price": 45.0, "to": "Eric F."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["disposed_at"] is not None
    assert body["disposed_via"] == "sold"
    assert body["disposed_price"] == 45.0
    assert body["disposed_to"] == "Eric F."


async def test_dispose_rejects_invalid_via(client):
    """A closed vocabulary is an enum, validated at the schema — 422 like
    style/size/condition, not a hand-rolled 400 in the service."""
    hat = await _make_hat(client)
    resp = await client.post(
        f"/api/hats/{hat['id']}/dispose", json={"via": "destroyed"}
    )
    assert resp.status_code == 422
    assert "destroyed" not in resp.text, "422 bodies must not echo the input"


async def test_undispose_clears_fields(client):
    hat = await _make_hat(client)
    await client.post(f"/api/hats/{hat['id']}/dispose", json={"via": "lost"})
    resp = await client.delete(f"/api/hats/{hat['id']}/dispose")
    assert resp.status_code == 200
    body = resp.json()
    assert body["disposed_at"] is None
    assert body["disposed_via"] is None


async def test_status_filter_excludes_disposed_by_default(client):
    a = await _make_hat(client)
    b = await _make_hat(client)
    await client.post(f"/api/hats/{b['id']}/dispose", json={"via": "sold", "price": 10})

    # Default: active only
    resp = await client.get("/api/hats")
    ids = [h["id"] for h in resp.json()]
    assert a["id"] in ids
    assert b["id"] not in ids

    # Explicit disposed
    resp = await client.get("/api/hats?status=disposed")
    ids = [h["id"] for h in resp.json()]
    assert a["id"] not in ids
    assert b["id"] in ids

    # All
    resp = await client.get("/api/hats?status=all")
    ids = [h["id"] for h in resp.json()]
    assert a["id"] in ids
    assert b["id"] in ids


async def test_disposed_hat_frees_case_slot(client):
    """Capacity validation must skip disposed hats."""
    case = (await client.post("/api/cases", json={"case_type": "archive"})).json()
    # Fill the case with 4 regular hats
    hats = []
    for _ in range(4):
        h = await _make_hat(client, case_id=case["id"])
        hats.append(h)

    # 5th hat into a full case → 409
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game", "case_id": case["id"]},
    )
    assert resp.status_code == 409

    # Dispose one of the existing hats
    await client.post(f"/api/hats/{hats[0]['id']}/dispose", json={"via": "sold"})

    # Now a new hat should fit (the disposed one no longer counts)
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game", "case_id": case["id"]},
    )
    assert resp.status_code == 201


@pytest.mark.anyio
async def test_restoring_into_a_full_case_still_leaves_the_hat_in_the_room(client):
    """A hat that no longer fits comes back loose IN THE ROOM, not nowhere.

    `undispose_hat` catches the capacity 409 and detaches. Until 2.57.1 it
    cleared `case_id` without setting `direct_room_id`, so a restored hat that
    did not fit was reachable only from the Hats list and search — the same bug
    `delete_case` had, at the second of the two detach sites. Lowering beanie
    capacity to 6 in 2.57.0 turned this from rare into routine.
    """
    room = (await client.post("/api/rooms", json={"name": "Loft"})).json()
    case = (await client.post(
        "/api/cases", json={"case_type": "daily_wear", "room_id": room["id"]}
    )).json()

    async def add_beanie():
        return await client.post("/api/hats", json={
            "condition": "new", "size": "classic", "style": "beanie",
            "case_id": case["id"],
        })

    hat = (await add_beanie()).json()
    await client.post(f"/api/hats/{hat['id']}/dispose", json={"via": "sold"})

    # Refill the freed slot and the rest of the case, so the restore cannot fit.
    for _ in range(capacity.MAX_BEANIE):
        assert (await add_beanie()).status_code == 201

    restored = await client.delete(f"/api/hats/{hat['id']}/dispose")
    assert restored.status_code == 200
    body = restored.json()

    assert body["case_id"] is None, "it genuinely does not fit"
    assert body["direct_room_id"] == room["id"], "but it is still in that room"
    assert body["room_id"] == room["id"]

    detail = (await client.get(f"/api/rooms/{room['id']}")).json()
    assert any(h["id"] == hat["id"] for h in detail["loose_hats"])
