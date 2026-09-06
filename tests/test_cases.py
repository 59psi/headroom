import pytest
from headroom.services import capacity


@pytest.mark.anyio
async def test_create_archive_case(client):
    resp = await client.post("/api/cases", json={"case_type": "archive"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["case_type"] == "archive"
    assert data["display_id"] == "A-001"
    assert data["sequence_number"] == 1
    assert data["hat_count"] == 0


@pytest.mark.anyio
async def test_create_daily_wear_case(client):
    resp = await client.post("/api/cases", json={"case_type": "daily_wear"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["display_id"] == "D-001"


@pytest.mark.anyio
async def test_sequential_ids(client):
    await client.post("/api/cases", json={"case_type": "archive"})
    await client.post("/api/cases", json={"case_type": "archive"})
    await client.post("/api/cases", json={"case_type": "daily_wear"})

    resp = await client.get("/api/cases")
    cases = resp.json()
    display_ids = [c["display_id"] for c in cases]
    assert "A-001" in display_ids
    assert "A-002" in display_ids
    assert "D-001" in display_ids


@pytest.mark.anyio
async def test_list_cases(client):
    await client.post("/api/cases", json={"case_type": "archive"})
    await client.post("/api/cases", json={"case_type": "daily_wear"})

    resp = await client.get("/api/cases")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.anyio
async def test_get_case_detail(client):
    await client.post("/api/cases", json={"case_type": "archive"})
    resp = await client.get("/api/cases/A-001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["display_id"] == "A-001"
    assert data["hats"] == []


@pytest.mark.anyio
async def test_get_case_not_found(client):
    resp = await client.get("/api/cases/A-999")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_update_case_type(client):
    await client.post("/api/cases", json={"case_type": "archive"})
    resp = await client.put("/api/cases/A-001", json={"case_type": "daily_wear"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["case_type"] == "daily_wear"
    assert data["display_id"] == "D-001"


@pytest.mark.anyio
async def test_delete_empty_case(client):
    await client.post("/api/cases", json={"case_type": "archive"})
    resp = await client.delete("/api/cases/A-001")
    assert resp.status_code == 204

    resp = await client.get("/api/cases")
    assert len(resp.json()) == 0


@pytest.mark.anyio
async def test_invalid_case_type(client):
    resp = await client.post("/api/cases", json={"case_type": "invalid"})
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_create_case_default_room(client):
    resp = await client.post("/api/cases", json={"case_type": "archive"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["room_id"] == 1
    assert data["room_name"] == "Default Room"


@pytest.mark.anyio
async def test_create_case_in_room(client):
    # Create a room first
    room_resp = await client.post("/api/rooms", json={"name": "Closet"})
    room_id = room_resp.json()["id"]

    resp = await client.post("/api/cases", json={"case_type": "archive", "room_id": room_id})
    assert resp.status_code == 201
    data = resp.json()
    assert data["room_id"] == room_id
    assert data["room_name"] == "Closet"


@pytest.mark.anyio
async def test_moving_a_case_to_a_real_room_works_and_a_missing_one_is_rejected(client):
    """Editing a case's room is the repair path for an orphaned case.

    Writing another bad id here would be the worst possible failure, so the
    same existence check as on create applies.
    """
    room = await client.post("/api/rooms", json={"name": "Bedroom"})
    room_id = room.json()["id"]
    case = await client.post("/api/cases", json={"case_type": "archive"})
    display_id = case.json()["display_id"]

    moved = await client.put(f"/api/cases/{display_id}", json={"room_id": room_id})
    assert moved.status_code == 200
    assert moved.json()["room_name"] == "Bedroom"

    rooms = {r["name"]: r["case_count"] for r in (await client.get("/api/rooms")).json()}
    assert rooms["Bedroom"] == 1, "the room it moved to must now count it"

    bad = await client.put(f"/api/cases/{display_id}", json={"room_id": 99999})
    assert bad.status_code == 404


@pytest.mark.anyio
async def test_case_read_reports_what_it_can_accept(client):
    """The picker grays out cases from these fields, so they must match the
    rule the write path enforces — a picker that disagrees produces a 409 on
    save with no warning, which at 40-60 cases is not something you can
    eyeball."""
    case = (await client.post("/api/cases", json={"case_type": "daily_wear"})).json()

    assert case["accepts_regular"] is True
    assert case["accepts_beanie"] is True
    assert case["free_regular"] == 3, "a three-hat case; melin's own order lines call it that"
    assert case["free_beanie"] == 6, "beanies squash flat — six to a case"

    # One regular hat in: still takes regular hats, no longer takes beanies.
    await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game", "case_id": case["id"],
    })
    after = (await client.get(f"/api/cases/{case['display_id']}")).json()

    assert after["accepts_regular"] is True
    assert after["free_regular"] == 2
    assert after["accepts_beanie"] is False, "type exclusivity must show in the read model"


@pytest.mark.anyio
async def test_a_full_case_reports_itself_full_but_still_takes_one_more(client):
    """Three is full. A fourth goes in — the case is then OVERFULL, not broken.

    Two distinct states that used to be one. "Full" is the number the case is
    designed around; the extra hat physically fits and people do it, so the
    save is allowed and the UI reports it rather than pretending 4 is normal
    or refusing something that works.
    """
    case = (await client.post("/api/cases", json={"case_type": "daily_wear"})).json()

    async def add():
        return await client.post("/api/hats", json={
            "condition": "new", "size": "classic", "style": "a_game", "case_id": case["id"],
        })

    for _ in range(capacity.MAX_REGULAR):
        assert (await add()).status_code == 201

    full = (await client.get(f"/api/cases/{case['display_id']}")).json()
    assert full["free_regular"] == 0, "no room left before it is overfull"
    assert full["overfull"] is False
    assert full["nominal_capacity"] == capacity.MAX_REGULAR
    assert full["accepts_regular"] is True, "the fourth still fits"

    assert (await add()).status_code == 201

    over = (await client.get(f"/api/cases/{case['display_id']}")).json()
    assert over["hat_count"] == 4
    assert over["overfull"] is True
    assert over["free_regular"] == 0
    assert over["accepts_regular"] is False, "one over is the whole allowance"

    # The fifth is refused, and the message quotes the ceiling actually
    # enforced rather than the nominal 3 it would already have exceeded.
    rejected = await add()
    assert rejected.status_code == 409
    assert "(4)" in rejected.json()["detail"]


@pytest.mark.anyio
async def test_a_disposed_hat_frees_its_slot_in_the_read_model(client):
    """Disposed hats stay in the database but free their slot.

    The occupancy shown must match: counting a disposed hat would render a
    case as fuller than the validator considers it, so the picker would gray
    out a case that a save would happily accept.
    """
    case = (await client.post("/api/cases", json={"case_type": "daily_wear"})).json()
    hat = (await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game", "case_id": case["id"],
    })).json()

    before = (await client.get(f"/api/cases/{case['display_id']}")).json()
    assert before["free_regular"] == 2

    await client.post(f"/api/hats/{hat['id']}/dispose", json={"via": "sold"})

    after = (await client.get(f"/api/cases/{case['display_id']}")).json()
    assert after["free_regular"] == capacity.MAX_REGULAR, "a disposed hat is still occupying a slot"
    assert after["hat_count"] == 0
    # The detail's hat LIST must agree with its own count. It did not: the
    # count filtered disposed hats and the list did not, so the case page
    # showed a sold hat as present under a header that said the case was empty.
    assert after["hats"] == [], "a disposed hat is still listed as being in the case"


@pytest.mark.anyio
async def test_deleting_a_case_leaves_its_hats_in_the_room(client):
    """A deleted case must not take its hats out of the room with it.

    Before 2.33 a hat with no case had no room either, so clearing `case_id`
    was the whole job. Now a hat can live in a room directly, and clearing
    only `case_id` left these hats reachable from nowhere but the Hats list
    and search — the shelf appeared to empty itself. The hats did not move;
    only their container went. `room_service.delete_room` has said the same
    thing about the symmetric operation since 2.33.
    """
    room = (await client.post("/api/rooms", json={"name": "Closet"})).json()
    case = (await client.post(
        "/api/cases", json={"case_type": "daily_wear", "room_id": room["id"]}
    )).json()
    hat = (await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game", "case_id": case["id"],
    })).json()

    assert (await client.delete(f"/api/cases/{case['display_id']}")).status_code in (200, 204)

    after = (await client.get(f"/api/hats/{hat['id']}")).json()
    assert after["case_id"] is None, "the case is gone, so the hat cannot still be in it"
    assert after["direct_room_id"] == room["id"], "the hat is still physically in that room"
    assert after["room_id"] == room["id"], "and must resolve a room for every room view"

    detail = (await client.get(f"/api/rooms/{room['id']}")).json()
    assert any(h["id"] == hat["id"] for h in detail["loose_hats"]), (
        "the room detail page is the only place a loose hat is browsable"
    )


@pytest.mark.anyio
async def test_deleting_a_case_does_not_file_its_disposed_hats_into_the_room(client):
    """`Case.hats` includes disposed hats; the room must not.

    Every other occupancy reader excludes them. Filing a disposed hat into a
    room puts it on a shelf it is not on — invisible until someone restores it,
    at which point it materializes as loose in a room it never occupied. The
    audit line must not count them either.
    """
    room = (await client.post("/api/rooms", json={"name": "Attic"})).json()
    case = (await client.post(
        "/api/cases", json={"case_type": "daily_wear", "room_id": room["id"]}
    )).json()

    async def add():
        return (await client.post("/api/hats", json={
            "condition": "new", "size": "classic", "style": "a_game",
            "case_id": case["id"],
        })).json()

    kept, sold = await add(), await add()
    await client.post(f"/api/hats/{sold['id']}/dispose", json={"via": "sold"})

    await client.delete(f"/api/cases/{case['display_id']}")

    assert (await client.get(f"/api/hats/{kept['id']}")).json()["direct_room_id"] == room["id"]
    gone = (await client.get(f"/api/hats/{sold['id']}?status=all")).json()
    assert gone["direct_room_id"] is None, "a disposed hat is not on any shelf"

    detail = (await client.get(f"/api/rooms/{room['id']}")).json()
    loose_ids = {h["id"] for h in detail["loose_hats"]}
    assert kept["id"] in loose_ids
    assert sold["id"] not in loose_ids
