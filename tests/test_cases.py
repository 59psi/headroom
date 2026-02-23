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
