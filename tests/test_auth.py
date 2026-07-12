"""Auth flows: first-run setup, login, rate limiting, sessions, API token,
passkeys (verification stubbed — no authenticator in CI), share links."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio

CREDS = {"username": "brandon", "password": "a-strong-password"}


async def _setup_owner(anon_client):
    resp = await anon_client.post("/api/auth/setup", json=CREDS)
    assert resp.status_code == 200, resp.text
    return resp


# ------------------------------ setup --------------------------------- #


async def test_status_reports_needs_setup_then_authenticated(anon_client):
    resp = await anon_client.get("/api/auth/status")
    assert resp.json() == {"needs_setup": True, "authenticated": False, "username": None}

    await _setup_owner(anon_client)  # sets the session cookie on the client

    resp = await anon_client.get("/api/auth/status")
    assert resp.json() == {
        "needs_setup": False, "authenticated": True, "username": "brandon",
    }


async def test_setup_only_works_once(anon_client):
    await _setup_owner(anon_client)
    resp = await anon_client.post(
        "/api/auth/setup", json={"username": "intruder", "password": "password123"}
    )
    assert resp.status_code == 403


async def test_protected_routes_401_until_setup_and_login(anon_client):
    for path in ("/api/hats", "/api/cases", "/api/settings/api-key", "/uploads/x.png"):
        resp = await anon_client.get(path)
        assert resp.status_code == 401, path
    # Health stays open for probes
    assert (await anon_client.get("/health")).status_code == 200


# ------------------------------ login --------------------------------- #


async def test_login_logout_cycle(anon_client):
    await _setup_owner(anon_client)
    anon_client.cookies.clear()

    resp = await anon_client.get("/api/hats")
    assert resp.status_code == 401

    resp = await anon_client.post("/api/auth/login", json=CREDS)
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is True

    assert (await anon_client.get("/api/hats")).status_code == 200

    assert (await anon_client.post("/api/auth/logout")).status_code == 204
    assert (await anon_client.get("/api/hats")).status_code == 401


async def test_login_wrong_password_and_rate_limit(anon_client):
    from headroom.services import auth_service

    auth_service._failures.clear()
    await _setup_owner(anon_client)
    anon_client.cookies.clear()

    bad = {"username": "brandon", "password": "wrong-password"}
    for _ in range(5):
        resp = await anon_client.post("/api/auth/login", json=bad)
        assert resp.status_code == 401
    # Sixth attempt — even with the RIGHT password — is locked out
    resp = await anon_client.post("/api/auth/login", json=CREDS)
    assert resp.status_code == 429
    auth_service._failures.clear()


async def test_me_returns_api_token_and_rotate(anon_client):
    await _setup_owner(anon_client)
    me = (await anon_client.get("/api/auth/me")).json()
    assert me["username"] == "brandon"
    assert me["api_token"].startswith("hr_")

    rotated = (await anon_client.post("/api/auth/token/rotate")).json()
    assert rotated["api_token"] != me["api_token"]

    # Old token dead, new token works (cookie-less)
    anon_client.cookies.clear()
    old = await anon_client.get(
        "/api/hats", headers={"Authorization": f"Bearer {me['api_token']}"}
    )
    assert old.status_code == 401
    new = await anon_client.get(
        "/api/hats", headers={"Authorization": f"Bearer {rotated['api_token']}"}
    )
    assert new.status_code == 200


async def test_change_password(anon_client):
    await _setup_owner(anon_client)
    resp = await anon_client.post(
        "/api/auth/password",
        json={"current_password": "nope", "new_password": "new-password-123"},
    )
    assert resp.status_code == 403
    resp = await anon_client.post(
        "/api/auth/password",
        json={"current_password": CREDS["password"], "new_password": "new-password-123"},
    )
    assert resp.status_code == 204

    anon_client.cookies.clear()
    assert (
        await anon_client.post("/api/auth/login", json=CREDS)
    ).status_code == 401
    assert (
        await anon_client.post(
            "/api/auth/login",
            json={"username": "brandon", "password": "new-password-123"},
        )
    ).status_code == 200


# ----------------------------- passkeys -------------------------------- #


async def test_passkey_register_and_login_with_stubbed_verify(anon_client, monkeypatch):
    await _setup_owner(anon_client)

    resp = await anon_client.post("/api/auth/passkeys/register/options")
    assert resp.status_code == 200
    body = resp.json()
    assert body["options"]["rp"]["id"] == "localhost"
    assert body["options"]["challenge"]

    monkeypatch.setattr(
        "headroom.services.passkey_service.verify_registration",
        lambda credential, challenge: {
            "credential_id": "cred-abc", "public_key": "pk-abc", "sign_count": 0,
        },
    )
    resp = await anon_client.post(
        "/api/auth/passkeys/register/verify",
        json={"state_id": body["state_id"], "credential": {"id": "cred-abc"}, "name": "iPhone"},
    )
    assert resp.status_code == 200

    listed = (await anon_client.get("/api/auth/passkeys")).json()
    assert [p["name"] for p in listed] == ["iPhone"]

    # Cookie-less passkey login
    anon_client.cookies.clear()
    opts = (await anon_client.post("/api/auth/passkeys/login/options")).json()
    monkeypatch.setattr(
        "headroom.services.passkey_service.verify_authentication",
        lambda credential, challenge, stored: stored.sign_count + 1,
    )
    resp = await anon_client.post(
        "/api/auth/passkeys/login/verify",
        json={"state_id": opts["state_id"], "credential": {"id": "cred-abc"}},
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "brandon"
    assert (await anon_client.get("/api/hats")).status_code == 200

    # Reusing the consumed challenge fails
    resp = await anon_client.post(
        "/api/auth/passkeys/login/verify",
        json={"state_id": opts["state_id"], "credential": {"id": "cred-abc"}},
    )
    assert resp.status_code == 400


# ---------------------------- share links ------------------------------ #


async def test_share_link_public_view_and_revoke(client, anon_client):
    hat = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    assert hat.status_code == 201

    created = await client.post("/api/share-links", json={"label": "My hats"})
    assert created.status_code == 201
    token = created.json()["token"]

    # Public view works WITHOUT auth
    resp = await anon_client.get(f"/api/public/share/{token}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] == "My hats"
    assert body["hat_count"] == 1

    # Bogus token 404s; management list requires auth
    assert (await anon_client.get("/api/public/share/bogus")).status_code == 404
    assert (await anon_client.get("/api/share-links")).status_code == 401

    # Revoke kills it
    link_id = (await client.get("/api/share-links")).json()[0]["id"]
    assert (await client.delete(f"/api/share-links/{link_id}")).status_code == 204
    assert (await anon_client.get(f"/api/public/share/{token}")).status_code == 404


async def test_change_password_revokes_other_sessions(anon_client, app):
    """Compromise response: a password change kills every OTHER session."""
    from httpx import ASGITransport, AsyncClient

    await _setup_owner(anon_client)  # session A on anon_client

    # Second device logs in → session B
    other = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    resp = await other.post("/api/auth/login", json=CREDS)
    assert resp.status_code == 200
    assert (await other.get("/api/hats")).status_code == 200

    # Device A changes the password
    resp = await anon_client.post(
        "/api/auth/password",
        json={"current_password": CREDS["password"], "new_password": "rotated-pass-99"},
    )
    assert resp.status_code == 204

    # A (the changer) survives; B is dead
    assert (await anon_client.get("/api/hats")).status_code == 200
    assert (await other.get("/api/hats")).status_code == 401
