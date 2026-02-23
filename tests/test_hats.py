import pytest


async def _create_case(client, case_type="archive"):
    resp = await client.post("/api/cases", json={"case_type": case_type})
    return resp.json()


async def _create_hat(client, **overrides):
    data = {
        "condition": "new",
        "size": "standard",
        "style": "a_game",
    }
    data.update(overrides)
    return await client.post("/api/hats", json=data)


@pytest.mark.anyio
async def test_create_hat_unassigned(client):
    resp = await _create_hat(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["case_id"] is None
    assert data["display_id"] is None
    assert data["is_beanie"] is False


@pytest.mark.anyio
async def test_create_hat_in_case(client):
    case = await _create_case(client)
    resp = await _create_hat(client, case_id=case["id"])
    assert resp.status_code == 201
    data = resp.json()
    assert data["case_id"] == case["id"]
    assert data["position_in_case"] == 1
    assert data["display_id"] == "A-001-01"
    assert data["case_display_id"] == "A-001"


@pytest.mark.anyio
async def test_hat_positions_sequential(client):
    case = await _create_case(client)
    await _create_hat(client, case_id=case["id"])
    resp = await _create_hat(client, case_id=case["id"])
    data = resp.json()
    assert data["position_in_case"] == 2
    assert data["display_id"] == "A-001-02"


@pytest.mark.anyio
async def test_create_beanie(client):
    resp = await _create_hat(client, style="beanie")
    assert resp.status_code == 201
    assert resp.json()["is_beanie"] is True


@pytest.mark.anyio
async def test_list_hats(client):
    await _create_hat(client)
    await _create_hat(client, style="beanie")
    resp = await client.get("/api/hats")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.anyio
async def test_list_hats_filter_by_style(client):
    await _create_hat(client, style="a_game")
    await _create_hat(client, style="beanie")
    resp = await client.get("/api/hats?style=beanie")
    assert len(resp.json()) == 1
    assert resp.json()[0]["style"] == "beanie"


@pytest.mark.anyio
async def test_get_hat(client):
    create_resp = await _create_hat(client)
    hat_id = create_resp.json()["id"]
    resp = await client.get(f"/api/hats/{hat_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == hat_id


@pytest.mark.anyio
async def test_get_hat_not_found(client):
    resp = await client.get("/api/hats/999")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_update_hat(client):
    create_resp = await _create_hat(client)
    hat_id = create_resp.json()["id"]
    resp = await client.put(
        f"/api/hats/{hat_id}", json={"condition": "worn"}
    )
    assert resp.status_code == 200
    assert resp.json()["condition"] == "worn"


@pytest.mark.anyio
async def test_delete_hat(client):
    create_resp = await _create_hat(client)
    hat_id = create_resp.json()["id"]
    resp = await client.delete(f"/api/hats/{hat_id}")
    assert resp.status_code == 204
    resp = await client.get(f"/api/hats/{hat_id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_assign_hat_to_case(client):
    case = await _create_case(client)
    create_resp = await _create_hat(client)
    hat_id = create_resp.json()["id"]
    resp = await client.patch(
        f"/api/hats/{hat_id}/assign", json={"case_id": case["id"]}
    )
    assert resp.status_code == 200
    assert resp.json()["case_id"] == case["id"]
    assert resp.json()["display_id"] == "A-001-01"


@pytest.mark.anyio
async def test_unassign_hat(client):
    case = await _create_case(client)
    create_resp = await _create_hat(client, case_id=case["id"])
    hat_id = create_resp.json()["id"]
    resp = await client.patch(
        f"/api/hats/{hat_id}/assign", json={"case_id": None}
    )
    assert resp.status_code == 200
    assert resp.json()["case_id"] is None
    assert resp.json()["display_id"] is None


@pytest.mark.anyio
async def test_hat_nonexistent_case(client):
    resp = await _create_hat(client, case_id=999)
    assert resp.status_code == 404
