"""Wear tracking + QR case-label sheet."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def _hat(client, **fields):
    resp = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game", **fields}
    )
    return resp.json()["id"]


async def test_wear_log_and_undo(client):
    hat_id = await _hat(client)

    resp = await client.post(f"/api/hats/{hat_id}/wear", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["wear_count"] == 1
    assert body["date_last_worn"] is not None

    # Same-day double tap is idempotent
    resp = await client.post(f"/api/hats/{hat_id}/wear", json={})
    assert resp.json()["wear_count"] == 1

    # Backdated wear counts separately; date_last_worn stays at the max
    resp = await client.post(f"/api/hats/{hat_id}/wear", json={"worn_at": "2024-01-05"})
    body = resp.json()
    assert body["wear_count"] == 2
    assert body["date_last_worn"] != "2024-01-05"

    # Undo removes the most recent (today), leaving the backdated one
    resp = await client.delete(f"/api/hats/{hat_id}/wear/latest")
    body = resp.json()
    assert body["wear_count"] == 1
    assert body["date_last_worn"] == "2024-01-05"


async def test_wear_rejected_for_disposed(client):
    hat_id = await _hat(client)
    await client.post(f"/api/hats/{hat_id}/dispose", json={"via": "sold"})
    resp = await client.post(f"/api/hats/{hat_id}/wear", json={})
    assert resp.status_code == 409


async def test_case_labels_sheet(client, anon_client):
    await client.post("/api/cases", json={"case_type": "archive", "capacity": 3})
    resp = await client.get("/api/admin/case-labels")
    assert resp.status_code == 200
    html = resp.text
    assert "<svg" in html and "A-001" in html and "0/3 hats" in html
    # Auth-gated like the rest of /api
    assert (await anon_client.get("/api/admin/case-labels")).status_code == 401
