"""Viewing a room shows what is in it — loose hats first.

Until 2.35 there was no room view at all: `/rooms` listed names with edit and
delete, and `GET /api/rooms/{id}` returned a name and a case count. So the
room-stored hats added in 2.33 had nowhere to be seen — the Cases tab reaches
a hat through its case, and a hat on a shelf has no case to be reached through.

Loose hats lead the response for that reason: they are the half of a room that
this view is the only home for.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def _room(client, name):
    resp = await client.post("/api/rooms", json={"name": name})
    assert resp.status_code == 201
    return resp.json()


async def _case(client, room_id):
    resp = await client.post(
        "/api/cases", json={"case_type": "archive", "room_id": room_id}
    )
    assert resp.status_code == 201
    return resp.json()


async def _hat(client, **fields):
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game", **fields},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_a_room_reports_its_loose_hats_and_its_cases(client):
    shelf = await _room(client, "Study")
    case = await _case(client, shelf["id"])
    await _hat(client, case_id=case["id"], model_name="Boxed")
    await _hat(client, room_id=shelf["id"], model_name="Loose")

    body = (await client.get(f"/api/rooms/{shelf['id']}")).json()

    assert [h["model_name"] for h in body["loose_hats"]] == ["Loose"]
    assert [c["display_id"] for c in body["cases"]] == [case["display_id"]]


async def test_a_cased_hat_is_not_listed_as_loose(client):
    """The distinction the whole view rests on."""
    shelf = await _room(client, "Study")
    case = await _case(client, shelf["id"])
    await _hat(client, case_id=case["id"], model_name="Boxed")

    body = (await client.get(f"/api/rooms/{shelf['id']}")).json()

    assert body["loose_hats"] == []
    assert body["cases"][0]["hat_count"] == 1


async def test_loose_hats_come_back_newest_first(client):
    """A hat set down loose is usually one you just handled, and this view is
    where you go to find it again."""
    shelf = await _room(client, "Study")
    await _hat(client, room_id=shelf["id"], model_name="Older")
    await _hat(client, room_id=shelf["id"], model_name="Newer")

    body = (await client.get(f"/api/rooms/{shelf['id']}")).json()

    assert [h["model_name"] for h in body["loose_hats"]] == ["Newer", "Older"]


async def test_a_disposed_loose_hat_is_left_out(client):
    shelf = await _room(client, "Study")
    hat = await _hat(client, room_id=shelf["id"], model_name="Gone")
    await client.post(f"/api/hats/{hat['id']}/dispose", json={"via": "sold"})

    body = (await client.get(f"/api/rooms/{shelf['id']}")).json()

    assert body["loose_hats"] == []


async def test_another_rooms_hats_are_not_included(client):
    study = await _room(client, "Study")
    attic = await _room(client, "Attic")
    await _hat(client, room_id=attic["id"], model_name="Upstairs")

    body = (await client.get(f"/api/rooms/{study['id']}")).json()

    assert body["loose_hats"] == []


async def test_the_rooms_list_carries_a_loose_count(client):
    """So the list can say a room holds something before you open it — a room
    with three loose hats and no cases used to read as empty."""
    shelf = await _room(client, "Study")
    await _hat(client, room_id=shelf["id"])
    await _hat(client, room_id=shelf["id"])

    rooms = (await client.get("/api/rooms")).json()

    row = next(r for r in rooms if r["id"] == shelf["id"])
    assert row["loose_hat_count"] == 2
    assert row["case_count"] == 0


async def test_the_loose_count_ignores_disposed_hats(client):
    shelf = await _room(client, "Study")
    hat = await _hat(client, room_id=shelf["id"])
    await client.post(f"/api/hats/{hat['id']}/dispose", json={"via": "sold"})

    rooms = (await client.get("/api/rooms")).json()

    assert next(r for r in rooms if r["id"] == shelf["id"])["loose_hat_count"] == 0


async def test_an_unknown_room_is_404(client):
    assert (await client.get("/api/rooms/9999")).status_code == 404
