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
