"""Security regression tests.

These exist so the most embarrassing bugs cannot silently come back. Each
test maps to a specific finding from the v0.2.0 archaeology pass.
"""

from __future__ import annotations

import re
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


# ---- Key endpoints accept a session ----------------------------------- #


async def test_set_api_key_accepts_a_session(client):
    """v1.0: key endpoints accept a session. (The anonymous half is covered by
    `test_every_api_path_is_gated_unless_it_is_on_the_allowlist`.)"""
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


# ---- The open set is a policy, so pin it -------------------------------- #


#: Every route path an anonymous caller is ALLOWED to reach. Anything the app
#: serves that is not matched here must answer 401.
#:
#: This list is the point of the test below. Authorization for ~85 data-bearing
#: endpoints rests on one `startswith` tuple in `auth.py`, and nothing asserted
#: what that tuple lets through — so a route added under a new top-level path,
#: or a prefix edited by one character, published collection data silently. It
#: had already happened: `/openapi.json`, `/docs` and `/redoc` begin with none
#: of the protected prefixes and served the entire route surface, every schema
#: and every field name to anonymous callers on an internet-facing deployment.
_ANONYMOUS_OK = (
    "/health",              # liveness + readiness, for the container check
    "/api/auth/",           # login, setup, status — the way in
    "/api/public/",         # branding logo, guest view, share links, CA cert
)

#: The SPA catch-all, which MUST answer anonymously or the login page cannot
#: render. It serves the shell and static assets only — every data call the
#: app then makes goes through `/api/`, which is gated. Listed separately from
#: the prefixes above because it is a whole-path match, not a prefix, and
#: because it is the one entry here that is load-bearing for being open.
_ANONYMOUS_OK_EXACT = ("/{full_path}",)


def _is_allowed_anonymous(path: str) -> bool:
    return path in _ANONYMOUS_OK_EXACT or any(
        path.startswith(p) for p in _ANONYMOUS_OK
    )


async def test_every_api_path_is_gated_unless_it_is_on_the_allowlist(anon_client, app):
    """Enumerate the app's OWN route table and probe each path anonymously.

    Deliberately driven from `app.openapi()` rather than a hand-written list:
    a hand-written list cannot notice a route that was added, which is the only
    failure mode that matters here. A new endpoint under a new prefix either
    lands on the allowlist above — a decision someone has to write down — or
    this test fails.

    Path parameters are filled with a value that cannot exist. A 404 is a pass:
    it means the gate let the request through to a handler that then found
    nothing, which is correct for an allowlisted path, and for a gated one the
    401 fires before the handler ever runs.
    """
    paths = app.openapi()["paths"]
    assert len(paths) > 50, "sanity: the route table should be substantial"

    unguarded: list[str] = []
    for raw_path, operations in paths.items():
        if _is_allowed_anonymous(raw_path):
            continue
        # `{hat_id}` → an id that will not resolve; `{token}` → junk.
        probe = re.sub(r"\{[^}]+\}", "999999999", raw_path)
        for method in operations:
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            resp = await anon_client.request(method.upper(), probe)
            if resp.status_code != 401:
                unguarded.append(f"{method.upper()} {raw_path} -> {resp.status_code}")

    assert not unguarded, (
        "these are reachable without authentication and are not on the "
        "allowlist in this file:\n  " + "\n  ".join(unguarded)
    )


async def test_the_schema_itself_is_not_public(anon_client):
    """`/openapi.json` is a map of the attack surface, and it was anonymous.

    101 paths, every schema, every field name, 130 KB, to anyone who could
    reach the port — while `/health/ready` next door redacts filesystem paths
    and key sources from the same caller. The gate is a prefix tuple and these
    three routes begin with none of the prefixes in it.
    """
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert (await anon_client.get(path)).status_code == 401, path


async def test_the_login_surface_stays_reachable(anon_client):
    """The other half: gating must not lock out the way in.

    A tighter gate that also blocked `/api/auth/status` would make the login
    page unable to render, which is the failure this pairs against.
    """
    assert (await anon_client.get("/api/auth/status")).status_code == 200
    assert (await anon_client.get("/health")).status_code == 200


async def test_the_blocked_key_tracker_is_actually_bounded():
    """`_MAX_TRACKED_KEYS` named a bound the code did not enforce.

    The only eviction was an age sweep — it removes entries older than
    `_LOCKOUT_SECONDS` and nothing else — so a burst that fills the dict faster
    than that window elapses removed nothing and it grew without limit.
    Measured before the hard cap existed: 10,000 keys survived a "bound" of
    4,096. It is fed by an unauthenticated endpoint, which is what makes the
    difference between a soft and a hard cap matter.
    """
    import time

    from headroom.services import auth_service

    auth_service._blocked_logged.clear()
    now = time.time()
    for i in range(10_000):
        auth_service._blocked_logged[f"key-{i}"] = now  # all FRESH, none expired

    auth_service.should_log_block("1.2.3.4", "someone")

    assert len(auth_service._blocked_logged) <= auth_service._MAX_TRACKED_KEYS, (
        "an age-only sweep is not a bound when nothing has aged"
    )
    auth_service._blocked_logged.clear()


async def test_share_tokens_are_redacted_from_the_access_log():
    """A share token is a 256-bit bearer credential in a URL PATH.

    So uvicorn's access log writes it in clear at INFO on every public request,
    into the same rotated file an operator greps and anything that ships those
    logs onward. It is the documented `?key=` incident one layer down — and
    `error_handler`'s "log the path, never the full URL, because query strings
    carry tokens" mitigation misses it precisely because this secret is not in
    the query.

    Redaction rather than a URL redesign: every link already handed out keeps
    working, which a scheme change would not.
    """
    import logging

    from headroom.app import _RedactShareTokens

    filt = _RedactShareTokens()
    token = "Ab3d-Ef7h_Ij1k2Lm3n4Op5q"

    # uvicorn's access log passes the request line as a %-style arg.
    rec = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/1.1" %d',
        ("1.2.3.4", "GET", f"/api/public/share/{token}/photo/7", 200),
        None,
    )
    filt.filter(rec)
    assert token not in str(rec.args), "the token survived in the log args"
    assert "<redacted>" in str(rec.args)

    # And when the message has already been interpolated.
    rec2 = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        f'GET /share/{token} 200', None, None,
    )
    filt.filter(rec2)
    assert token not in rec2.msg
    assert "<redacted>" in rec2.msg

    # A path with no token is left exactly as it was — a redactor that
    # rewrites ordinary paths makes the log harder to read for no gain.
    rec3 = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "GET /api/hats 200", None, None,
    )
    filt.filter(rec3)
    assert rec3.msg == "GET /api/hats 200"
