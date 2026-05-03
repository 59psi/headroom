"""Tests for the API-key management endpoints."""

import pytest


@pytest.mark.anyio
async def test_api_key_initially_unconfigured(client):
    resp = await client.get("/api/settings/api-key")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is False
    assert data["source"] is None
    assert data["masked"] is None


@pytest.mark.anyio
async def test_set_api_key_returns_masked_value(client):
    resp = await client.put(
        "/api/settings/api-key", json={"api_key": "sk-ant-test-1234567890"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["source"] == "database"
    assert data["masked"] is not None
    assert "sk-ant-test-1234567890" not in data["masked"]
    # Masked format: prefix … suffix
    assert data["masked"].startswith("sk-an")
    assert data["masked"].endswith("7890")


@pytest.mark.anyio
async def test_delete_api_key(client):
    await client.put(
        "/api/settings/api-key", json={"api_key": "sk-ant-test-1234567890"}
    )
    resp = await client.delete("/api/settings/api-key")
    assert resp.status_code == 204
    resp = await client.get("/api/settings/api-key")
    assert resp.json()["configured"] is False


@pytest.mark.anyio
async def test_test_api_key_without_key(client):
    resp = await client.post("/api/settings/api-key/test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "No API key" in data["detail"]


@pytest.mark.anyio
async def test_reanalyze_without_api_key(client):
    """Reanalyze should 400 cleanly if no key + a photo exists."""
    create = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game"},
    )
    hat_id = create.json()["id"]

    # No photo yet → 400
    resp = await client.post(f"/api/hats/{hat_id}/reanalyze")
    assert resp.status_code == 400
