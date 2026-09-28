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


async def test_the_documented_forgot_password_recovery_works(anon_client, db_session):
    """Delete the owner row and sessions; setup must run again.

    The first-run sentinel (`app_settings.owner_setup_done`) serializes setup
    against a racing second POST and was never removed, so the recovery
    OPERATIONS.md documents — `DELETE FROM users; DELETE FROM auth_sessions;` —
    brought the setup form back (`needs_setup` counts users) and then answered
    it with "Setup already completed". Reproduced in review; a sentinel that
    outlives the row it guards is the bug, so setup clears a stale one.
    """
    from sqlalchemy import delete

    from headroom.models.user import AuthSession, User

    await _setup_owner(anon_client)
    anon_client.cookies.clear()

    # Exactly the two documented statements — nothing about the sentinel.
    await db_session.execute(delete(AuthSession))
    await db_session.execute(delete(User))
    await db_session.commit()

    status = (await anon_client.get("/api/auth/status")).json()
    assert status["needs_setup"] is True, "the form comes back"

    resp = await anon_client.post(
        "/api/auth/setup", json={"username": "brandon", "password": "a-new-password-1"}
    )
    assert resp.status_code == 200, resp.text
    # And it is still single-shot afterwards.
    assert (
        await anon_client.post(
            "/api/auth/setup", json={"username": "intruder", "password": "password123"}
        )
    ).status_code == 403


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


async def test_an_unknown_username_costs_the_same_argon2_work_as_a_wrong_password(
    anon_client, monkeypatch
):
    """The login must not tell an attacker WHICH username is the owner's.

    `user is None or not await verify_password_async(...)` short-circuits: a
    name that does not exist skipped argon2 entirely and answered in ~4 ms
    where the real name with a wrong password took ~36 ms (hundreds of ms on
    a Pi). The limiter keys on (ip, username), so rotating candidate names
    never locks, and the timing gap reads out half of the credential on the
    first try per name. A timing assertion would flake; what is pinned is the
    MECHANISM — argon2 runs against a placeholder hash when there is no user,
    so both branches do the same work.
    """
    from headroom.services import auth_service

    auth_service._failures.clear()
    await _setup_owner(anon_client)
    anon_client.cookies.clear()

    calls: list[tuple[str, str]] = []
    real_verify = auth_service.verify_password_async

    async def spying_verify(password_hash: str, password: str) -> bool:
        calls.append((password_hash, password))
        return await real_verify(password_hash, password)

    monkeypatch.setattr(auth_service, "verify_password_async", spying_verify)

    resp = await anon_client.post(
        "/api/auth/login", json={"username": "nobody-here", "password": "whatever"}
    )
    assert resp.status_code == 401
    assert len(calls) == 1, "argon2 must run for an unknown username too"
    placeholder_hash, _ = calls[0]
    assert placeholder_hash.startswith("$argon2"), placeholder_hash
    # The placeholder is a real hash of something nobody types, so the verify
    # does the full work AND can never accidentally succeed.
    assert await real_verify(placeholder_hash, "whatever") is False
    auth_service._failures.clear()


async def test_the_session_cookie_carries_the_flags_the_whole_csrf_defense_rests_on(anon_client):
    """There is no CSRF token and no Origin check: `SameSite=Lax` IS the
    defense, `HttpOnly` is what keeps a script injection from reading the
    session, and `Secure` is what keeps it off plain HTTP once TLS is on.

    A mutation inverting all three survived the full suite — a regression
    dropping any of them would have shipped green. The attributes are read
    off the raw `Set-Cookie` header, since the cookie jar keeps the value and
    forgets the flags.
    """
    await _setup_owner(anon_client)
    anon_client.cookies.clear()

    resp = await anon_client.post("/api/auth/login", json=CREDS)
    assert resp.status_code == 200
    cookie = resp.headers["set-cookie"]
    attrs = {part.strip().split("=", 1)[0].lower() for part in cookie.split(";")}

    assert cookie.startswith("headroom_session=")
    assert "httponly" in attrs
    assert "samesite=lax" in cookie.lower()
    assert "path=/" in cookie.lower()
    assert "max-age=" in cookie.lower()
    # The test transport is plain http, so `Secure` must be ABSENT here — set
    # unconditionally it would drop the cookie on the http80 overlay and on
    # `http://<ip>:8000`, the zero-config remote path.
    assert "secure" not in attrs


async def test_the_secure_flag_follows_the_scheme():
    """`Secure` is decided by the request scheme, not hardcoded either way.

    The ASGI test transport is plain http and does not honor
    `X-Forwarded-Proto`, so the https branch is exercised on the cookie
    setter directly with a synthetic scope of each scheme.
    """
    from fastapi import Response
    from starlette.requests import Request

    from headroom.routes.auth import _set_session_cookie

    def cookie_for(scheme: str) -> str:
        scope = {
            "type": "http", "method": "POST", "path": "/api/auth/login", "scheme": scheme,
            "headers": [], "query_string": b"", "server": ("h", 443 if scheme == "https" else 80),
        }
        response = Response()
        _set_session_cookie(response, Request(scope), "sid")
        return response.headers["set-cookie"].lower()

    assert "secure" in cookie_for("https")
    assert "secure" not in cookie_for("http")


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


async def test_the_password_confirmation_routes_are_not_an_unlimited_oracle(
    client, db_session
):
    """Reveal, rotate and change-password each check the password — and none
    of them used to limit or record a wrong one.

    Measured before: 30 wrong passwords against each route from one session
    answered 30 × 403 in under two seconds and wrote no audit row, while the
    login next door locked after five. A stolen cookie could brute-force the
    owner's password at argon2 speed, invisibly, and a hit reveals the API
    token that outlives every session revocation.

    The three routes share the LOGIN's bucket for this account and address:
    five wrong answers across any mix of them lock all three, and the login,
    even to the right password. Every wrong answer is audited; the lockout is
    audited once, not once per blocked attempt.
    """
    from sqlalchemy import func, select

    from headroom.models.activity_log import ActivityLog

    async def rows(kind: str) -> int:
        db_session.expire_all()
        return (await db_session.execute(
            select(func.count(ActivityLog.id)).where(ActivityLog.kind == kind)
        )).scalar_one()

    wrong = "definitely-not-it"
    attempts = [
        ("/api/auth/token/reveal", {"current_password": wrong}),
        ("/api/auth/token/rotate", {"current_password": wrong}),
        ("/api/auth/password", {"current_password": wrong, "new_password": "whatever-123"}),
        ("/api/auth/token/reveal", {"current_password": wrong}),
        ("/api/auth/token/rotate", {"current_password": wrong}),
    ]
    for path, body in attempts:
        resp = await client.post(path, json=body)
        assert resp.status_code == 403, f"{path}: {resp.status_code} {resp.text}"

    assert await rows("auth.reauth_failed") == 5, "each wrong password must be audited"

    # Locked now — on every door that checks this password, the right answer
    # included, so a lucky sixth guess cannot land.
    right = "test-password-123"
    for path, body in (
        ("/api/auth/token/reveal", {"current_password": right}),
        ("/api/auth/token/rotate", {"current_password": right}),
        ("/api/auth/password", {"current_password": right, "new_password": "whatever-123"}),
    ):
        resp = await client.post(path, json=body)
        assert resp.status_code == 429, f"{path} was not locked: {resp.status_code}"
        assert "api_token" not in resp.text
    login = await client.post(
        "/api/auth/login", json={"username": "testowner", "password": right}
    )
    assert login.status_code == 429, "a separate bucket doubles the guesses per window"

    assert await rows("auth.reauth_blocked") == 1, (
        "the lockout must be audited once per window, not once per blocked attempt"
    )


async def test_a_successful_login_clears_the_failures_before_it(anon_client):
    """The owner who fumbles the password and then gets it right is not an
    attacker — the next fumble must not inherit the earlier ones.

    Four misses, a success, then four more misses and the right password: with
    the success clearing the bucket, that last login is fine. Without it, the
    fifth miss in total locks the account for fifteen minutes, one typo after
    a login that worked.
    """
    await _setup_owner(anon_client)
    anon_client.cookies.clear()
    bad = {"username": "brandon", "password": "wrong-password"}

    for _ in range(4):
        assert (await anon_client.post("/api/auth/login", json=bad)).status_code == 401
    assert (await anon_client.post("/api/auth/login", json=CREDS)).status_code == 200
    for _ in range(4):
        assert (await anon_client.post("/api/auth/login", json=bad)).status_code == 401

    resp = await anon_client.post("/api/auth/login", json=CREDS)
    assert resp.status_code == 200, "a success did not clear the failures before it"


async def test_the_auth_routes_audit_through_the_activity_service_seam(
    anon_client, monkeypatch
):
    """`activity_service.log_activity` is THE seam for audit rows — patched
    there, every route must see the patch.

    `routes/auth.py` imported the function by name, so it held its own
    reference: with the module attribute patched, the settings routes went
    through the patch and a failed login still wrote its row through the real
    function. A test that relied on the seam would have been blind to exactly
    the unauthenticated route it most needed to see.
    """
    from headroom.services import activity_service

    seen: list[str] = []

    async def recording(db, *, kind, **_kw):
        seen.append(kind)

    monkeypatch.setattr(activity_service, "log_activity", recording)

    resp = await anon_client.post(
        "/api/auth/login", json={"username": "nobody-here", "password": "wrong-password"}
    )

    assert resp.status_code == 401
    assert seen == ["auth.login_failed"], seen


# ----------------------------- passkeys -------------------------------- #


@pytest.mark.parametrize(
    ("sent", "stored"),
    [
        ("  ", "Passkey"),
        ("\u202eenohPi", "enohPi"),
        ("x" * 200, "x" * 80),
    ],
    ids=["blank", "bidi-override", "overlong"],
)
async def test_a_passkey_name_is_cleaned_and_cut_never_refused(
    anon_client, monkeypatch, sent, stored
):
    """The name arrives AFTER the authenticator created the credential, so
    the server must take it: blank is "Passkey", a bidi override is dropped
    (it stored verbatim, and read reversed in the list), and an overlong name
    is cut to the column rather than refused — a 422 here would leave a
    passkey on the device the server never registered."""
    await _setup_owner(anon_client)
    body = (await anon_client.post("/api/auth/passkeys/register/options")).json()
    monkeypatch.setattr(
        "headroom.services.passkey_service.verify_registration",
        lambda credential, challenge: {
            "credential_id": "cred-name", "public_key": "pk", "sign_count": 0,
        },
    )

    resp = await anon_client.post(
        "/api/auth/passkeys/register/verify",
        json={"state_id": body["state_id"], "credential": {"id": "cred-name"}, "name": sent},
    )

    assert resp.status_code == 200, resp.text
    listed = (await anon_client.get("/api/auth/passkeys")).json()
    assert [p["name"] for p in listed] == [stored]


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


@pytest.mark.parametrize(
    "credential",
    [
        {"id": ["x"]},
        {"id": {"a": 1}},
        {"id": 12345},
        {"id": None},
        {"id": ""},
        {"id": "x" * 2000},
        {},
    ],
    ids=["list", "object", "number", "null", "empty", "oversize", "missing"],
)
async def test_a_malformed_passkey_id_is_refused_without_an_error_row(
    anon_client, db_session, credential
):
    """The anonymous passkey login looks the credential up by `credential["id"]`.

    `credential` is an open dict — it is the browser's object, handed to the
    passkey library — so the id arrived unchecked, and a list or an object
    reached the SQL bind and raised: a 500, and a durable `error.unhandled`
    activity row, per anonymous request. Measured: 100 requests in 0.7 s, 100
    rows. The id is now a bounded string by schema, so anything else is a 422
    before the route runs — and a 422 writes nothing.
    """
    from sqlalchemy import func, select

    from headroom.models.activity_log import ActivityLog

    opts = (await anon_client.post("/api/auth/passkeys/login/options")).json()
    resp = await anon_client.post(
        "/api/auth/passkeys/login/verify",
        json={"state_id": opts["state_id"], "credential": credential},
    )

    assert resp.status_code == 422, resp.text
    errors = (await db_session.execute(
        select(func.count(ActivityLog.id)).where(ActivityLog.kind == "error.unhandled")
    )).scalar_one()
    assert errors == 0, "a malformed passkey id wrote an unhandled-error row"


async def test_an_unknown_but_well_formed_passkey_id_is_still_a_401(anon_client):
    """The schema check narrows what reaches the lookup; it does not replace it."""
    opts = (await anon_client.post("/api/auth/passkeys/login/options")).json()
    resp = await anon_client.post(
        "/api/auth/passkeys/login/verify",
        json={"state_id": opts["state_id"], "credential": {"id": "never-registered"}},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Unknown passkey"


async def test_one_account_cannot_delete_anothers_passkey(client, app, db_session, monkeypatch):
    """`row.user_id != user.id` is the only thing between a session and every
    other account's passkeys — and deleting that half of the check left the
    whole suite green, because no test ever had a second account.

    Single-owner is how the app is used, not something the schema enforces:
    the `users` table takes any number of rows. The answer is a 404, the same
    as a passkey that does not exist, so the id space cannot be probed.
    """
    from datetime import datetime, timedelta, timezone

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select

    from headroom.models.user import AuthSession, PasskeyCredential, User

    opts = (await client.post("/api/auth/passkeys/register/options")).json()
    monkeypatch.setattr(
        "headroom.services.passkey_service.verify_registration",
        lambda credential, challenge: {
            "credential_id": "owners-cred", "public_key": "pk", "sign_count": 0,
        },
    )
    assert (await client.post(
        "/api/auth/passkeys/register/verify",
        json={"state_id": opts["state_id"], "credential": {"id": "owners-cred"}, "name": "Owner"},
    )).status_code == 200
    passkey_id = (await client.get("/api/auth/passkeys")).json()[0]["id"]

    other = User(username="someone-else", password_hash="x", api_token="hr_other-token")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    db_session.add(AuthSession(
        id="other-session", user_id=other.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    ))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as intruder:
        intruder.cookies.set("headroom_session", "other-session")
        resp = await intruder.delete(f"/api/auth/passkeys/{passkey_id}")

    assert resp.status_code == 404, resp.text
    db_session.expire_all()
    still_there = (await db_session.execute(
        select(PasskeyCredential).where(PasskeyCredential.id == passkey_id)
    )).scalar_one_or_none()
    assert still_there is not None, "another account deleted the owner's passkey"


async def test_a_second_passkey_can_be_registered(anon_client, monkeypatch):
    """The second passkey is where registration used to 500.

    With one credential stored, `registration_options` builds a non-empty
    `exclude_credentials`; py_webauthn serializes each entry by attribute, so
    the plain dicts the code used to pass raised AttributeError inside
    `options_to_json`. Every "Face ID on another device" attempt hit it, and
    the only tested path was the first passkey, where the list is empty.
    """
    await _setup_owner(anon_client)
    first = (await anon_client.post("/api/auth/passkeys/register/options")).json()
    monkeypatch.setattr(
        "headroom.services.passkey_service.verify_registration",
        lambda credential, challenge: {
            "credential_id": "cred-abc", "public_key": "pk-abc", "sign_count": 0,
        },
    )
    assert (
        await anon_client.post(
            "/api/auth/passkeys/register/verify",
            json={"state_id": first["state_id"], "credential": {"id": "cred-abc"}, "name": "iPhone"},
        )
    ).status_code == 200

    second = await anon_client.post("/api/auth/passkeys/register/options")
    assert second.status_code == 200, second.text
    excluded = second.json()["options"]["excludeCredentials"]
    assert [c["id"] for c in excluded] == ["cred-abc"]
    assert excluded[0]["type"] == "public-key"


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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
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


async def test_rotating_usernames_from_one_address_is_still_locked_out(
    anon_client, db_session
):
    """The limiter keyed on (ip, username) and nothing else.

    Credential stuffing rotates the username, so no pair ever reached five
    failures: measured over HTTP, 300 attempts at `nobody0…299` from one
    address ran at 412/s with zero 429s, and each one committed an
    `auth.login_failed` row — an fsync on the SD card, per anonymous request,
    unbounded — plus a limiter key that lived fifteen minutes (200,000
    rotated names in-process = 200,000 keys, still not limited). 2.77.0
    applied exactly this reasoning to the BLOCKED row and left the FAILED row
    with it. A second bucket keyed on the address alone closes it: the pair
    bucket still gives the owner five tries at their own name, and the
    address bucket bounds everything an anonymous client can make this
    endpoint do.
    """
    from sqlalchemy import func, select

    from headroom.models.activity_log import ActivityLog
    from headroom.services import auth_service

    async def failed_rows() -> int:
        return (await db_session.execute(
            select(func.count(ActivityLog.id)).where(ActivityLog.kind == "auth.login_failed")
        )).scalar_one()

    auth_service._failures.clear()
    auth_service._blocked_logged.clear()
    await _setup_owner(anon_client)
    anon_client.cookies.clear()

    codes = []
    for i in range(auth_service._MAX_FAILURES_PER_IP + 10):
        resp = await anon_client.post(
            "/api/auth/login", json={"username": f"nobody{i}", "password": "x" * 8}
        )
        codes.append(resp.status_code)

    assert codes.count(401) == auth_service._MAX_FAILURES_PER_IP, codes
    assert codes[auth_service._MAX_FAILURES_PER_IP:] == [429] * 10, (
        "the address bucket never engaged — rotating the username is free"
    )
    # Bounded: the failed rows stop where the 401s stop, and the block is
    # audited once for the address rather than once per new username.
    assert await failed_rows() == auth_service._MAX_FAILURES_PER_IP
    blocked = (await db_session.execute(
        select(func.count(ActivityLog.id)).where(ActivityLog.kind == "auth.login_blocked")
    )).scalar_one()
    assert blocked == 1
    # And the RIGHT credentials from that address are locked too — that is
    # what a lockout is; the owner waits out the window like anyone else.
    assert (await anon_client.post("/api/auth/login", json=CREDS)).status_code == 429
    # Keys are bounded with it: one per attempt that got through, plus the
    # address bucket, not one per attempt made.
    assert len(auth_service._failures) <= auth_service._MAX_FAILURES_PER_IP + 1

    auth_service._failures.clear()
    auth_service._blocked_logged.clear()


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
