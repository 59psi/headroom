"""Auth flows: first-run setup, login, rate limiting, sessions, API token,
passkeys (verification stubbed — no authenticator in CI), share links."""

from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.anyio

CREDS = {"username": "brandon", "password": "a-strong-password"}


async def _setup_owner(anon_client):
    resp = await anon_client.post("/api/auth/setup", json=CREDS)
    assert resp.status_code == 200, resp.text
    return resp


# ------------------------------ setup --------------------------------- #


async def test_setup_is_gated_when_a_setup_token_is_configured(anon_client, monkeypatch):
    """Until the owner claims it, `/setup` hands full control to whoever posts first.

    `GET /api/auth/status` publishes `needs_setup: true`, so the window is
    advertised rather than merely open — and on the Let's Encrypt overlay the
    hostname reaches a public certificate-transparency log within seconds, so
    "whoever gets there first" is not limited to the LAN.

    Opt-in: unset, nothing changes for the LAN install, which the other tests
    in this file cover.
    """
    monkeypatch.setenv("HEADROOM_SETUP_TOKEN", "s3cret-claim")

    missing = await anon_client.post("/api/auth/setup", json=CREDS)
    assert missing.status_code == 403
    wrong = await anon_client.post(
        "/api/auth/setup", json={**CREDS, "setup_token": "guess"}
    )
    assert wrong.status_code == 403

    # A rejection must not reveal that the box is merely unclaimed — an
    # attacker learning the token is WRONG has learned it is worth returning to.
    assert wrong.json()["detail"] == "Setup already completed"
    assert (await anon_client.get("/api/auth/status")).json()["needs_setup"] is True

    ok = await anon_client.post(
        "/api/auth/setup", json={**CREDS, "setup_token": "s3cret-claim"}
    )
    assert ok.status_code == 200, ok.text


async def test_the_setup_token_does_not_gate_login(anon_client, monkeypatch):
    """`setup_token` rides on `Credentials`, which `/login` also takes.

    One schema for both is deliberate — two would drift on the fields that
    matter — but it must not become an accidental second factor on the endpoint
    used every day.
    """
    await _setup_owner(anon_client)
    monkeypatch.setenv("HEADROOM_SETUP_TOKEN", "s3cret-claim")
    anon_client.cookies.clear()

    resp = await anon_client.post("/api/auth/login", json=CREDS)
    assert resp.status_code == 200, resp.text


async def test_status_reports_needs_setup_then_authenticated(anon_client):
    resp = await anon_client.get("/api/auth/status")
    # Exact equality, deliberately: this payload is served to anyone who can
    # reach the login screen, so a field appearing here should have to be
    # written down rather than slipping in.
    # `guest_view_enabled` is ABSENT, not False: returning False would tell an
    # anonymous caller "this install has a guest mode, switched off", which is
    # the fact the guest routes' 404-rather-than-403 exists to keep private.
    assert resp.json() == {
        "needs_setup": True, "authenticated": False, "username": None,
    }

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


async def test_the_profile_does_not_carry_the_bearer_token(anon_client):
    """A session must not be enough to read a credential that outlives it.

    `/me` used to return `api_token`, and the Settings card fetches `/me` on
    every load — so the value was on the wire constantly. Sessions can be
    revoked (logout, password change, `destroy_other_sessions`); the API token
    cannot be reached by any of those, so anything holding a session could
    upgrade itself to access that survives every revocation available.

    Exact equality on the key set, not just `"api_token" not in me`: this is a
    withheld-field assertion, and those only hold if adding a field is what
    fails the test.
    """
    await _setup_owner(anon_client)
    me = (await anon_client.get("/api/auth/me")).json()

    assert set(me) == {"username", "token_set"}
    assert me["username"] == "brandon"
    assert me["token_set"] is True


async def test_reading_or_rotating_the_token_needs_the_password(anon_client):
    """Both, not just reveal — rotate RETURNS the new token.

    Gating reveal alone would be theater: an attacker holding a session could
    mint a fresh long-lived credential and read it straight back out of the
    rotate response, which is the identical escalation by a different verb.
    """
    await _setup_owner(anon_client)

    for path in ("/api/auth/token/reveal", "/api/auth/token/rotate"):
        wrong = await anon_client.post(path, json={"current_password": "not-it"})
        assert wrong.status_code == 403, f"{path} accepted a bad password"
        assert "api_token" not in wrong.text

    revealed = (await anon_client.post(
        "/api/auth/token/reveal", json={"current_password": CREDS["password"]}
    )).json()
    assert revealed["api_token"].startswith("hr_")

    rotated = (await anon_client.post(
        "/api/auth/token/rotate", json={"current_password": CREDS["password"]}
    )).json()
    assert rotated["api_token"] != revealed["api_token"]

    # Old token dead, new token works (cookie-less)
    anon_client.cookies.clear()
    old = await anon_client.get(
        "/api/hats", headers={"Authorization": f"Bearer {revealed['api_token']}"}
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


async def test_a_blocked_login_is_audited_once_per_window_not_once_per_attempt(
    anon_client, db_session
):
    """The 429 branch commits a durable row BEFORE raising.

    So the limiter was not stopping the write — it only changed which row got
    written. One row per request, from an unauthenticated endpoint, retained
    90 days: an anonymous client on the LAN could fill the SD card, which is
    exactly the condition `/health/ready`'s disk floor exists to catch and
    this app would have been the cause of.
    """
    from sqlalchemy import func, select

    from headroom.models.activity_log import ActivityLog
    from headroom.services import auth_service

    async def blocked_rows() -> int:
        return (await db_session.execute(
            select(func.count(ActivityLog.id)).where(
                ActivityLog.kind == "auth.login_blocked"
            )
        )).scalar_one()

    # The limiter is process-global in-memory, so this test must leave it as
    # it found it — 20 deliberate failures otherwise 429 whatever runs next.
    auth_service._failures.clear()
    auth_service._blocked_logged.clear()

    codes = []
    for _ in range(20):
        resp = await anon_client.post(
            "/api/auth/login", json={"username": "testowner", "password": "wrong-one"}
        )
        codes.append(resp.status_code)

    assert 429 in codes, "the limiter never engaged, so this proves nothing"
    blocked_attempts = codes.count(429)
    rows = await blocked_rows()

    assert rows >= 1, "a block must still be auditable"
    assert rows < blocked_attempts, (
        f"{rows} audit rows for {blocked_attempts} blocked attempts — an "
        "anonymous caller still writes one durable row per request"
    )

    auth_service._failures.clear()
    auth_service._blocked_logged.clear()


async def test_a_share_link_expires_unless_you_ask_for_forever(client):
    """The dangerous option must not be the one you get by not choosing.

    A share link is unscoped and whole-collection: every hat, with photos, and
    the room and case each lives in. Forwarded once, that is a permanent,
    room-by-room, photographed inventory of somebody's valuables — and the
    default was no expiry at all, so the easiest link to create was the one
    that never stops working.

    `null` still means never. That is a decision somebody can make; it just has
    to be made.
    """
    from headroom.schemas.share import DEFAULT_SHARE_EXPIRY_DAYS

    default = (await client.post("/api/share-links", json={"label": "default"})).json()
    forever = (await client.post(
        "/api/share-links", json={"label": "forever", "expires_days": None}
    )).json()

    links = {row["label"]: row for row in (await client.get("/api/share-links")).json()}
    assert links["default"]["expires_at"] is not None, (
        "omitting expires_days produced a link that never expires"
    )
    assert links["forever"]["expires_at"] is None, (
        "an explicit null must still mean never — the two cases have to stay "
        "distinguishable or the default silently overrides the choice"
    )

    expires = datetime.fromisoformat(links["default"]["expires_at"])
    created = datetime.fromisoformat(links["default"]["created_at"])
    assert round((expires - created).total_seconds() / 86400) == DEFAULT_SHARE_EXPIRY_DAYS

    # Both links work now; the point is only when they stop.
    for row in (default, forever):
        assert (await client.get(f"/api/public/share/{row['token']}")).status_code == 200
