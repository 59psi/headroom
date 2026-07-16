"""Tests for the append-only activity log."""

import pytest

pytestmark = pytest.mark.anyio


async def test_creating_a_hat_emits_log(client):
    created = (await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )).json()
    resp = await client.get("/api/admin/activity-log")
    assert resp.status_code == 200
    rows = resp.json()
    # Tie the audit row to THIS hat — not merely "a hat.created row exists
    # somewhere". A logger that fired with the wrong entity_id (or twice) would
    # sail past a bare membership check but is exactly the audit bug that matters.
    created_rows = [
        r for r in rows
        if r["kind"] == "hat.created" and r["entity_id"] == created["id"]
    ]
    assert len(created_rows) == 1, rows
    assert created_rows[0]["entity_type"] == "hat"


async def test_dispose_emits_log_with_via(client):
    hat = (await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )).json()
    await client.post(f"/api/hats/{hat['id']}/dispose", json={"via": "sold", "price": 50})
    resp = await client.get("/api/admin/activity-log?kind=hat.disposed")
    rows = resp.json()
    assert len(rows) == 1
    assert "sold" in rows[0]["summary"].lower()
    assert rows[0]["entity_id"] == hat["id"]


async def test_count_endpoint(client):
    await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    resp = await client.get("/api/admin/activity-log/count")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1
