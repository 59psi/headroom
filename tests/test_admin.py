"""Tests for the admin endpoints (recent errors + backup) and model setting."""

import pytest

pytestmark = pytest.mark.anyio


# ---- Model setting -------------------------------------------------- #


async def test_get_model_returns_default_when_unset(client):
    resp = await client.get("/api/settings/model")
    assert resp.status_code == 200
    body = resp.json()
    assert body["model_id"]  # non-empty
    assert body["source"] in ("default", "environment")


async def test_set_model_persists(client):
    resp = await client.put("/api/settings/model", json={"model_id": "claude-sonnet-4-5"})
    assert resp.status_code == 200
    assert resp.json() == {"model_id": "claude-sonnet-4-5", "source": "database"}

    # GET reflects the change
    resp = await client.get("/api/settings/model")
    assert resp.json()["model_id"] == "claude-sonnet-4-5"
    assert resp.json()["source"] == "database"


async def test_clear_model_falls_back_to_default(client):
    await client.put("/api/settings/model", json={"model_id": "claude-opus-4-7"})
    resp = await client.delete("/api/settings/model")
    assert resp.status_code == 204
    resp = await client.get("/api/settings/model")
    assert resp.json()["source"] in ("default", "environment")


async def test_set_model_validates_length(client):
    resp = await client.put("/api/settings/model", json={"model_id": "ab"})  # too short
    assert resp.status_code == 422


# ---- Recent errors -------------------------------------------------- #


async def test_recent_errors_empty_initially(client):
    resp = await client.get("/api/admin/recent-errors")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_recent_errors_count_endpoint(client):
    resp = await client.get("/api/admin/recent-errors/count")
    assert resp.status_code == 200
    assert resp.json() == {"count": 0}


# ---- Backup --------------------------------------------------------- #


async def test_backup_download_returns_gzip_attachment(client):
    resp = await client.get("/api/admin/backup")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/gzip"
    assert "attachment" in resp.headers["content-disposition"]
    # Should be a non-empty gzip — 2 bytes minimum (the gzip magic header alone is 2)
    assert len(resp.content) > 100


async def test_list_backups_empty_initially(client):
    resp = await client.get("/api/admin/backups")
    assert resp.status_code == 200
    assert resp.json() == []


# ---- Admin auth gate ------------------------------------------------ #


async def test_admin_endpoints_require_auth(client, anon_client):
    """v1.0: admin routes need a session cookie or a bearer API token."""
    # Anonymous → 401 (client fixture seeds the owner; anon has no cookie)
    resp = await anon_client.get("/api/admin/recent-errors")
    assert resp.status_code == 401

    # Wrong bearer token → 401
    resp = await anon_client.get(
        "/api/admin/recent-errors", headers={"Authorization": "Bearer wrong"}
    )
    assert resp.status_code == 401

    # Valid session cookie → 200
    resp = await client.get("/api/admin/recent-errors")
    assert resp.status_code == 200

    # Valid API token (the seeded owner's) → 200
    resp = await anon_client.get(
        "/api/admin/recent-errors",
        headers={"Authorization": "Bearer hr_test-api-token"},
    )
    assert resp.status_code == 200
