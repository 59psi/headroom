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


# ---------------------------- Logo serving ---------------------------- #


@pytest.mark.anyio
async def test_uploads_mount_survives_missing_dir_at_import(tmp_path, monkeypatch):
    """Fresh-install bug: uploads/ may not exist when create_app() runs.

    The lifespan creates the directory and seeds the default logo *after* the
    app factory has run, so the /uploads mount must not be gated on the
    directory already existing — otherwise the logo 404s until a restart.
    """
    from httpx import ASGITransport, AsyncClient

    from headroom.app import create_app
    from headroom.config import settings as app_settings
    from tests.conftest import _TEST_SESSION_ID, _seed_owner, test_session_factory

    # Distinct from the autouse isolated_upload_dir fixture's pre-created path —
    # this test specifically needs a directory that does NOT exist yet.
    upload_dir = tmp_path / "first-boot-uploads"
    assert not upload_dir.exists()
    monkeypatch.setattr(app_settings, "upload_dir", upload_dir)

    app = create_app()
    app.state.session_factory = test_session_factory
    await _seed_owner()

    # Simulate what the lifespan does on first boot: create dirs + seed logo
    branding = upload_dir / "branding"
    branding.mkdir(parents=True, exist_ok=True)
    (branding / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("headroom_session", _TEST_SESSION_ID)
        resp = await client.get("/uploads/branding/logo.png")
    assert resp.status_code == 200, (
        "seeded logo must be served on first boot, not only after a restart"
    )
    # Without the /uploads mount the SPA catch-all serves index.html with a
    # 200 — a "successful" broken image. Require the actual PNG bytes.
    assert resp.content == b"\x89PNG\r\n\x1a\n"
