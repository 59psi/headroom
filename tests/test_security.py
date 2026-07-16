"""Security regression tests.

These exist so the most embarrassing bugs cannot silently come back. Each
test maps to a specific finding from the v0.2.0 archaeology pass.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# All tests in this module use the autouse async setup_db fixture, so the
# anyio plugin has to be active even for synchronous-style tests.
pytestmark = pytest.mark.anyio


# ---- Path traversal in SPA fallback (was: app.py:55-61) ---------------- #


def _make_app_with_dist(tmp_path: Path):
    """Build a FastAPI app that serves a tmp directory as the SPA bundle."""
    from fastapi.testclient import TestClient

    import headroom.app as app_mod

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>")
    (dist / "assets").mkdir()
    (dist / "assets" / "ok.js").write_text("// ok")

    secret = tmp_path / "secret.txt"
    secret.write_text("DO NOT LEAK")

    # Point the app's frontend root at our tmp dist for this test
    monkey_orig = app_mod.FRONTEND_DIST
    app_mod.FRONTEND_DIST = dist.resolve()
    try:
        app = app_mod.create_app()
        return TestClient(app), dist, secret
    finally:
        app_mod.FRONTEND_DIST = monkey_orig


async def test_spa_does_not_serve_files_outside_dist(tmp_path):
    """Path traversal MUST NOT escape the frontend bundle.

    Acceptable outcomes for a traversal payload: 404, or fall back to
    index.html (200). Returning the contents of the file outside the dist
    is the bug — anchor of CRITICAL Sentinel S1.
    """
    client, _dist, secret = _make_app_with_dist(tmp_path)
    payloads = [
        "../secret.txt",
        "..%2fsecret.txt",
        "%2e%2e%2fsecret.txt",
        "../../etc/passwd",
        f"../{secret.name}",
    ]
    for p in payloads:
        resp = client.get(f"/{p}")
        assert "DO NOT LEAK" not in resp.text, f"traversal escaped dist with {p!r}"
        assert resp.status_code in (200, 404)


# ---- Admin-token guard on /api/settings/api-key ------------------------ #


async def test_set_api_key_requires_session(client, anon_client):
    """v1.0: key endpoints reject anonymous requests; sessions pass."""
    resp = await anon_client.put(
        "/api/settings/api-key", json={"api_key": "sk-ant-foo-bar-12345"}
    )
    assert resp.status_code == 401

    resp = await client.put(
        "/api/settings/api-key", json={"api_key": "sk-ant-foo-bar-12345"}
    )
    assert resp.status_code == 200
    assert resp.json()["configured"] is True


async def test_uploads_require_session(client, anon_client):
    """The /uploads static mount is gated — photos are collection data."""
    resp = await anon_client.get("/uploads/branding/logo.png")
    assert resp.status_code == 401


# ---- Path traversal in the public share-photo streamer ----------------- #


async def test_share_photo_streamer_blocks_path_traversal(client, anon_client, db_session):
    """The token-gated share-photo streamer must refuse any path that escapes
    the upload dir — even when the escape rides in on a hat's stored
    photo_path. Same `is_relative_to` guard as the SPA handler (Sentinel S1),
    but a different endpoint that had no regression test until now.
    """
    from headroom.config import settings
    from headroom.models.hat import Hat

    secret = settings.upload_dir.parent / "traversal-secret.txt"
    secret.write_text("DO NOT LEAK")

    hat = (await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )).json()
    # Force a stored path that resolves OUTSIDE the uploads root.
    row = await db_session.get(Hat, hat["id"])
    row.photo_path = f"../{secret.name}"
    await db_session.commit()

    token = (await client.post("/api/share-links", json={"label": "x"})).json()["token"]

    resp = await anon_client.get(f"/api/public/share/{token}/photo/{hat['id']}")
    assert "DO NOT LEAK" not in resp.text, "traversal leaked a file outside uploads"
    assert resp.status_code == 404
