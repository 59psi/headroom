"""A hat can live in a room with no case.

Rooms contain Cases contain Hats was the entire model, so `Hat.room` walked
`self.case.room` and a caseless hat reported no room at all — it was nowhere.
That is not how a collection actually sits: Caddies and Aviators do not fit a
three-hat travel case, special editions get displayed rather than packed, and
plenty of hats are simply out on a shelf.

The invariant these pin: a hat has a case OR a direct room, never both. A cased
hat's room IS its case's room, so a second stored answer is one that can
disagree.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def _room(client, name):
    resp = await client.post("/api/rooms", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _case(client, room_id=None):
    body = {"case_type": "archive"}
    if room_id is not None:
        body["room_id"] = room_id
    resp = await client.post("/api/cases", json=body)
    assert resp.status_code == 201
    return resp.json()


async def _hat(client, **fields):
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game", **fields},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_a_hat_can_be_created_straight_into_a_room(client):
    shelf = await _room(client, "Study shelf")

    hat = await _hat(client, style="caddy", room_id=shelf["id"])

    assert hat["case_id"] is None
    assert hat["direct_room_id"] == shelf["id"]
    assert hat["room_id"] == shelf["id"], "room_id must resolve without a case"
    assert hat["room_name"] == "Study shelf"
    # No case means no position, so no display id — the same as any uncased hat.
    assert hat["display_id"] is None


async def test_any_style_can_live_in_a_room(client):
    """Caddies and Aviators are why this exists, but nothing is restricted —
    a hat is out of its case for whatever reason its owner has."""
    shelf = await _room(client, "Shelf")

    for style in ("caddy", "aviator", "a_game", "beanie", "journey"):
        hat = await _hat(client, style=style, room_id=shelf["id"])
        assert hat["room_id"] == shelf["id"], f"{style} could not be room-stored"


async def test_assigning_to_a_room_removes_it_from_its_case(client):
    """The invariant. Both set would be two answers that can disagree."""
    room = await _room(client, "Landing")
    case = await _case(client)
    hat = await _hat(client, case_id=case["id"])
    assert hat["case_id"] == case["id"]

    resp = await client.patch(
        f"/api/hats/{hat['id']}/assign", json={"room_id": room["id"]}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["case_id"] is None
    assert body["position_in_case"] is None
    assert body["direct_room_id"] == room["id"]
    assert body["room_id"] == room["id"]


async def test_assigning_to_a_case_clears_the_direct_room(client):
    """The other direction: a cased hat takes its case's room, so the direct
    one must not linger and shadow it."""
    shelf = await _room(client, "Shelf")
    display = await _room(client, "Display")
    case = await _case(client, room_id=display["id"])
    hat = await _hat(client, room_id=shelf["id"])

    body = (await client.patch(
        f"/api/hats/{hat['id']}/assign", json={"case_id": case["id"]}
    )).json()

    assert body["direct_room_id"] is None, "stale direct room survived"
    assert body["room_id"] == display["id"], "room must follow the case"


async def test_a_case_wins_when_both_are_sent(client):
    """A caller sending both hasn't said which they meant; the case is the more
    specific placement."""
    shelf = await _room(client, "Shelf")
    case = await _case(client)
    hat = await _hat(client)

    body = (await client.patch(
        f"/api/hats/{hat['id']}/assign",
        json={"case_id": case["id"], "room_id": shelf["id"]},
    )).json()

    assert body["case_id"] == case["id"]
    assert body["direct_room_id"] is None


async def test_a_hat_can_be_taken_out_of_everything(client):
    shelf = await _room(client, "Shelf")
    hat = await _hat(client, room_id=shelf["id"])

    body = (await client.patch(f"/api/hats/{hat['id']}/assign", json={})).json()

    assert body["case_id"] is None
    assert body["direct_room_id"] is None
    assert body["room_id"] is None


async def test_creating_with_both_ignores_the_room(client):
    """A cased hat's room is its case's room — storing the other would be
    storing something that can disagree with it."""
    shelf = await _room(client, "Shelf")
    display = await _room(client, "Display")
    case = await _case(client, room_id=display["id"])

    hat = await _hat(client, case_id=case["id"], room_id=shelf["id"])

    assert hat["direct_room_id"] is None
    assert hat["room_id"] == display["id"]


async def test_an_unknown_room_is_rejected(client):
    hat = await _hat(client)
    resp = await client.patch(f"/api/hats/{hat['id']}/assign", json={"room_id": 9999})
    assert resp.status_code == 404


async def test_deleting_a_room_moves_its_caseless_hats(client):
    """They are not reachable through any case, so the case sweep misses them —
    and left behind they would point at a room that no longer exists, which
    reads as the hat vanishing from every room view while still existing."""
    doomed = await _room(client, "Spare room")
    hat = await _hat(client, room_id=doomed["id"])

    assert (await client.delete(f"/api/rooms/{doomed['id']}")).status_code == 204

    body = (await client.get(f"/api/hats/{hat['id']}")).json()
    assert body["room_id"] is not None, "hat was orphaned onto a deleted room"
    assert body["room_name"]


async def test_a_room_stored_hat_is_not_in_any_case(client):
    """It must not start occupying case capacity from a distance."""
    shelf = await _room(client, "Shelf")
    case = await _case(client)
    await _hat(client, room_id=shelf["id"])

    read = (await client.get(f"/api/cases/{case['display_id']}")).json()
    assert read["hat_count"] == 0


# ------------------------------ limited edition ----------------------------- #


async def test_limited_edition_defaults_off_and_can_be_set(client):
    """Not derived from anything: a hat is limited because the drop was, which
    no photo and no other field can tell you."""
    plain = await _hat(client)
    assert plain["limited_edition"] is False

    special = await _hat(client, limited_edition=True)
    assert special["limited_edition"] is True


async def test_limited_edition_can_be_toggled(client):
    hat = await _hat(client)

    on = (await client.put(
        f"/api/hats/{hat['id']}", json={"limited_edition": True}
    )).json()
    assert on["limited_edition"] is True

    off = (await client.put(
        f"/api/hats/{hat['id']}", json={"limited_edition": False}
    )).json()
    assert off["limited_edition"] is False


async def test_limited_edition_survives_an_unrelated_edit(client):
    """`exclude_unset` means an untouched field must not be reset to its
    default by a PUT that never mentioned it."""
    hat = await _hat(client, limited_edition=True)

    body = (await client.put(
        f"/api/hats/{hat['id']}", json={"model_name": "Coronado"}
    )).json()

    assert body["limited_edition"] is True
    assert body["model_name"] == "Coronado"
