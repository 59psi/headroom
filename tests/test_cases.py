import pytest


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
    """The picker greys out cases from these fields, so they must match the
    rule the write path enforces — a picker that disagrees produces a 409 on
    save with no warning, which at 40-60 cases is not something you can
    eyeball."""
    case = (await client.post("/api/cases", json={"case_type": "daily_wear"})).json()

    assert case["accepts_regular"] is True
    assert case["accepts_beanie"] is True
    assert case["free_regular"] == 4
    assert case["free_beanie"] == 6

    # One regular hat in: still takes regular hats, no longer takes beanies.
    await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game", "case_id": case["id"],
    })
    after = (await client.get(f"/api/cases/{case['display_id']}")).json()

    assert after["accepts_regular"] is True
    assert after["free_regular"] == 3
    assert after["accepts_beanie"] is False, "type exclusivity must show in the read model"


@pytest.mark.anyio
async def test_a_full_case_reports_itself_full(client):
    """Four regular hats is the default ceiling."""
    case = (await client.post("/api/cases", json={"case_type": "daily_wear"})).json()
    for _ in range(4):
        await client.post("/api/hats", json={
            "condition": "new", "size": "classic", "style": "a_game", "case_id": case["id"],
        })

    full = (await client.get(f"/api/cases/{case['display_id']}")).json()

    assert full["accepts_regular"] is False
    assert full["free_regular"] == 0
    # And the write path agrees — this is the 409 the picker now prevents.
    rejected = await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game", "case_id": case["id"],
    })
    assert rejected.status_code == 409


@pytest.mark.anyio
async def test_a_disposed_hat_frees_its_slot_in_the_read_model(client):
    """Disposed hats stay in the database but free their slot.

    The occupancy shown must match: counting a disposed hat would render a
    case as fuller than the validator considers it, so the picker would grey
    out a case that a save would happily accept.
    """
    case = (await client.post("/api/cases", json={"case_type": "daily_wear"})).json()
    hat = (await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game", "case_id": case["id"],
    })).json()

    before = (await client.get(f"/api/cases/{case['display_id']}")).json()
    assert before["free_regular"] == 3

    await client.post(f"/api/hats/{hat['id']}/dispose", json={"via": "sold"})

    after = (await client.get(f"/api/cases/{case['display_id']}")).json()
    assert after["free_regular"] == 4, "a disposed hat is still occupying a slot"
    assert after["hat_count"] == 0
