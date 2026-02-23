import pytest


async def _create_case(client, case_type="archive"):
    resp = await client.post("/api/cases", json={"case_type": case_type})
    return resp.json()


async def _create_hat(client, **overrides):
    data = {"condition": "new", "size": "standard", "style": "a_game"}
    data.update(overrides)
    return await client.post("/api/hats", json=data)


@pytest.mark.anyio
async def test_regular_hat_capacity_limit(client):
    case = await _create_case(client)
    for _ in range(4):
        resp = await _create_hat(client, case_id=case["id"])
        assert resp.status_code == 201

    # 5th regular hat should fail
    resp = await _create_hat(client, case_id=case["id"])
    assert resp.status_code == 409
    assert "regular hat capacity" in resp.json()["detail"]


@pytest.mark.anyio
async def test_beanie_capacity_limit(client):
    case = await _create_case(client)
    for _ in range(6):
        resp = await _create_hat(client, case_id=case["id"], style="beanie")
        assert resp.status_code == 201

    # 7th beanie should fail
    resp = await _create_hat(client, case_id=case["id"], style="beanie")
    assert resp.status_code == 409
    assert "beanie capacity" in resp.json()["detail"]


@pytest.mark.anyio
async def test_mixed_capacity(client):
    """A case can hold 4 regular + 6 beanies simultaneously."""
    case = await _create_case(client)
    for _ in range(4):
        resp = await _create_hat(client, case_id=case["id"], style="a_game")
        assert resp.status_code == 201
    for _ in range(6):
        resp = await _create_hat(client, case_id=case["id"], style="beanie")
        assert resp.status_code == 201

    # Both at max
    resp = await _create_hat(client, case_id=case["id"], style="a_game")
    assert resp.status_code == 409
    resp = await _create_hat(client, case_id=case["id"], style="beanie")
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_assign_respects_capacity(client):
    case = await _create_case(client)
    for _ in range(4):
        await _create_hat(client, case_id=case["id"])

    # Create unassigned hat, try to assign
    resp = await _create_hat(client)
    hat_id = resp.json()["id"]
    resp = await client.patch(
        f"/api/hats/{hat_id}/assign", json={"case_id": case["id"]}
    )
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_delete_case_with_hats_blocked(client):
    case = await _create_case(client)
    await _create_hat(client, case_id=case["id"])
    resp = await client.delete(f"/api/cases/{case['display_id']}")
    assert resp.status_code == 409
