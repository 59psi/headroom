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


def _make_app_with_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build a FastAPI app that serves a tmp directory as the SPA bundle.

    `FRONTEND_DIST` has to stay patched for the lifetime of the REQUESTS, not
    just while the app is built: `app._safe_spa_path` and the index fallback
    both read the module global per request.

    This helper used to set it, build the app, and restore it in a `finally`
    *before returning the client* — so every request the test then made was
    served from the real `frontend/dist`. The secret file below was unreachable
    whatever `safe_join` did, and the traversal assertion could not fail. It
    passed for the same reason an empty test passes. `monkeypatch` undoes the
    patch at teardown instead, which is after the requests.
    """
    from fastapi.testclient import TestClient

    import headroom.app as app_mod

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>")
    (dist / "assets").mkdir()
    (dist / "assets" / "ok.js").write_text("// ok")
    # A file at the dist ROOT, so fetching it goes through the SPA catch-all
    # and therefore through `_safe_spa_path` — the function under test. Files
    # under /assets are served by a StaticFiles mount bound at `create_app()`
    # time, so they answer even when the request-time global is unpatched, and
    # a canary built on one proves nothing about the other.
    (dist / "canary.txt").write_text("SERVED FROM TMP DIST")

    secret = tmp_path / "secret.txt"
    secret.write_text("DO NOT LEAK")

    # Point the app's frontend root at our tmp dist for this test.
    monkeypatch.setattr(app_mod, "FRONTEND_DIST", dist.resolve())
    return TestClient(app_mod.create_app()), dist, secret


async def test_spa_does_not_serve_files_outside_dist(tmp_path, monkeypatch):
    """Path traversal MUST NOT escape the frontend bundle.

    Acceptable outcomes for a traversal payload: 404, or fall back to
    index.html (200). Returning the contents of the file outside the dist
    is the bug — anchor of CRITICAL Sentinel S1.
    """
    client, _dist, secret = _make_app_with_dist(tmp_path, monkeypatch)

    # Prove the app is actually serving OUR tmp dist before concluding
    # anything from what it refuses to serve. Without this the test has no way
    # to distinguish "traversal was blocked" from "the payload was never
    # anywhere near the secret", which is the state it silently sat in.
    assert client.get("/canary.txt").text == "SERVED FROM TMP DIST", (
        "FRONTEND_DIST is not patched at REQUEST time — the traversal "
        "assertions below would pass without testing anything"
    )

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


@pytest.mark.anyio
async def test_security_headers_are_present_on_every_response(client):
    """Hardening headers, applied once in middleware rather than per-route."""
    resp = await client.get("/health")

    _assert_hardening_headers(resp)


@pytest.mark.anyio
async def test_security_headers_survive_the_auth_gate_401(anon_client):
    """The 401 is a response too — and the one strangers actually receive.

    `add_middleware` prepends, so the LAST middleware added is outermost.
    SecurityHeadersMiddleware was added first, which put it *behind* the auth
    gate: the gate short-circuits an unauthenticated /api/* request with its
    own 401 and that response never reached the header middleware. An
    anonymous GET /api/hats came back with two headers, content-type and
    content-length.

    The test that was named for this invariant asserted against /health, which
    the gate lets through — so the invariant it pinned was the one path where
    it already held.
    """
    resp = await anon_client.get("/api/hats")

    assert resp.status_code == 401
    _assert_hardening_headers(resp)


def _assert_hardening_headers(resp) -> None:
    csp = resp.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    # script-src must NOT allow inline — that is the directive that actually
    # blocks reflected XSS, and the one an over-broad policy quietly loosens.
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"


@pytest.mark.anyio
async def test_hsts_is_not_set_by_the_app(client):
    """HSTS from the app would pin a LAN hostname to HTTPS in the browser.

    The primary deployment is plain http:// on a LAN. A single HSTS response
    would make that hostname HTTPS-only for its max-age and lock the owner out
    of their own app. Caddy adds it on the internet-facing overlay instead.
    """
    resp = await client.get("/health")

    assert "strict-transport-security" not in {k.lower() for k in resp.headers}


@pytest.mark.anyio
async def test_unauthenticated_api_probe_is_logged(anon_client, caplog):
    """The only unauthenticated way to probe the API used to be silent.

    Login is rate-limited and audited; sweeping tokens at any other endpoint
    produced no record at all.
    """
    with caplog.at_level("WARNING"):
        resp = await anon_client.get("/api/hats")

    assert resp.status_code == 401
    assert "Rejected unauthenticated" in caplog.text
    assert "/api/hats" in caplog.text


@pytest.mark.anyio
async def test_the_401_log_never_contains_the_credential(anon_client, caplog):
    """Logging a token to diagnose token abuse is its own vulnerability."""
    secret = "hr_super-secret-token-value"
    with caplog.at_level("WARNING"):
        await anon_client.get("/api/hats", headers={"Authorization": f"Bearer {secret}"})

    assert secret not in caplog.text


# ---- POST /share is a two-line auth special case ----------------------- #


async def test_the_share_target_requires_auth_but_the_share_page_does_not(anon_client):
    """`/share` matches no protected prefix — two lines in `auth.py` guard it.

    `POST /share` writes DB rows and spools up to 100 files to disk; `GET
    /share/<token>` is the public share page and must stay open. That asymmetry
    was carried entirely by `if path == "/share" and request.method == "POST"`
    with NO test touching it: both existing callers used the authenticated
    fixture, so deleting those two lines left the suite green and the endpoint
    unauthenticated.
    """
    posted = await anon_client.post(
        "/share", files=[("photos", ("a.jpg", b"\xff\xd8\xff", "image/jpeg"))]
    )
    assert posted.status_code == 401, "the share TARGET must not be open"

    # The public share page keeps working — a bad token is a 404 from the SPA
    # route, never a 401, or sharing a link would demand a login.
    page = await anon_client.get("/share/some-token")
    assert page.status_code != 401, "the public share page must stay open"
