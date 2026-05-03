"""Tests for hat disposition (sold/gifted/lost) tracking."""

import pytest

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
    hat = await _make_hat(client)
    resp = await client.post(
        f"/api/hats/{hat['id']}/dispose", json={"via": "destroyed"}
    )
    assert resp.status_code == 400


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
