import pytest


@pytest.mark.anyio
async def test_default_room_exists(client):
    resp = await client.get("/api/rooms")
    assert resp.status_code == 200
    rooms = resp.json()
    assert len(rooms) >= 1
    default = next(r for r in rooms if r["id"] == 1)
    assert default["name"] == "Default Room"


@pytest.mark.anyio
async def test_create_room(client):
    resp = await client.post("/api/rooms", json={"name": "Bedroom"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Bedroom"
    assert data["case_count"] == 0


@pytest.mark.anyio
async def test_rename_room(client):
    resp = await client.post("/api/rooms", json={"name": "Old Name"})
    room_id = resp.json()["id"]

    resp = await client.put(f"/api/rooms/{room_id}", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


@pytest.mark.anyio
async def test_delete_room_reassigns(client):
    # Create a room and a case in it
    resp = await client.post("/api/rooms", json={"name": "Temp Room"})
    room_id = resp.json()["id"]

    resp = await client.post("/api/cases", json={"case_type": "archive", "room_id": room_id})
    assert resp.status_code == 201
    case_display_id = resp.json()["display_id"]

    # Delete the room
    resp = await client.delete(f"/api/rooms/{room_id}")
    assert resp.status_code == 204

    # Case should now be in default room
    resp = await client.get(f"/api/cases/{case_display_id}")
    assert resp.json()["room_id"] == 1


@pytest.mark.anyio
async def test_cannot_delete_default_room(client):
    resp = await client.delete("/api/rooms/1")
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_exactly_one_room_is_default(client):
    """The flag is the invariant the fallback logic depends on — zero flagged
    rooms breaks case creation, two makes the reassignment target ambiguous."""
    await client.post("/api/rooms", json={"name": "Garage"})
    rooms = (await client.get("/api/rooms")).json()
    assert [r["is_default"] for r in rooms].count(True) == 1
    assert next(r for r in rooms if r["is_default"])["id"] == 1


@pytest.mark.anyio
async def test_default_can_be_reassigned_and_old_default_deleted(client):
    """The whole point of the flag: the original default stops being special
    once another room takes the role, so it can finally be deleted."""
    garage = (await client.post("/api/rooms", json={"name": "Garage"})).json()

    # Blocked while room 1 still holds the flag.
    assert (await client.delete("/api/rooms/1")).status_code == 400

    resp = await client.post(f"/api/rooms/{garage['id']}/default")
    assert resp.status_code == 200
    assert resp.json()["is_default"] is True

    # Flag moved, so it is now the *new* default that is protected...
    assert (await client.delete(f"/api/rooms/{garage['id']}")).status_code == 400
    # ...and the original is deletable.
    assert (await client.delete("/api/rooms/1")).status_code == 204

    rooms = (await client.get("/api/rooms")).json()
    assert [r["id"] for r in rooms] == [garage["id"]]
    assert rooms[0]["is_default"] is True


@pytest.mark.anyio
async def test_cases_follow_the_current_default_not_id_1(client):
    """Both the reassignment target and the new-case default must resolve from
    the flag. Hardcoding 1 would send cases to a room that no longer exists."""
    garage = (await client.post("/api/rooms", json={"name": "Garage"})).json()
    await client.post(f"/api/rooms/{garage['id']}/default")

    # New case with no room named → lands in the current default, not room 1.
    case = (await client.post("/api/cases", json={"case_type": "archive"})).json()
    assert case["room_id"] == garage["id"]

    # A deleted room's cases reassign to the current default too.
    temp = (await client.post("/api/rooms", json={"name": "Temp"})).json()
    orphan = (await client.post(
        "/api/cases", json={"case_type": "daily_wear", "room_id": temp["id"]}
    )).json()
    assert (await client.delete(f"/api/rooms/{temp['id']}")).status_code == 204

    moved = (await client.get(f"/api/cases/{orphan['display_id']}")).json()
    assert moved["room_id"] == garage["id"]


@pytest.mark.anyio
async def test_get_room_by_id(client):
    resp = await client.get("/api/rooms/1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 1
    assert data["name"] == "Default Room"


@pytest.mark.anyio
async def test_get_room_not_found(client):
    resp = await client.get("/api/rooms/9999")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_rooms_meta_endpoint(client):
    resp = await client.get("/api/meta/rooms")
    assert resp.status_code == 200
    data = resp.json()
    assert any(r["label"] == "Default Room" for r in data)
