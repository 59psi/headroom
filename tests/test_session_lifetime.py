"""Session lifetime and the login lockout window — the numbers OPERATIONS §6
states ("30-day expiry", "5 failures → 15-minute lockout") and the code that
holds them.

Every one of these was a mutation that survived the whole suite: the expiry
check replaced with `if False:`, the prune cutoff moved to 1970, the TTL raised
from 30 days to ten years, the lockout shortened from fifteen minutes to five.
The suite seeded sessions a day into the future and never presented an expired
one, never called the prune, and never asked how long a lockout lasts.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from headroom.models.user import AuthSession, User
from headroom.services import auth_service

pytestmark = pytest.mark.anyio


async def _owner(db_session) -> User:
    return (await db_session.execute(select(User))).scalars().one()


async def _add_session(db_session, user: User, sid: str, expires_at: datetime) -> None:
    db_session.add(AuthSession(id=sid, user_id=user.id, expires_at=expires_at))
    await db_session.commit()


async def _session_ids(db_session) -> set[str]:
    db_session.expire_all()
    return set((await db_session.execute(select(AuthSession.id))).scalars().all())


# ------------------------------ expiry -------------------------------- #


async def test_an_expired_session_is_refused_and_its_row_deleted(app, client, db_session):
    """Presenting a session past its `expires_at` is a 401, and the row goes.

    The row is a credential; keeping it after it stopped being honored is
    keeping authentication material for nothing.
    """
    user = await _owner(db_session)
    await _add_session(
        db_session, user, "expired-session",
        datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    stale = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    stale.cookies.set(auth_service.SESSION_COOKIE, "expired-session")
    try:
        assert (await stale.get("/api/hats")).status_code == 401
    finally:
        await stale.aclose()

    assert "expired-session" not in await _session_ids(db_session)
    # The owner's live session is untouched — only the expired one was acted on.
    assert (await client.get("/api/hats")).status_code == 200


async def test_a_session_just_short_of_expiry_still_works(app, client, db_session):
    """The boundary from the other side: `expires_at` in the future is valid."""
    user = await _owner(db_session)
    await _add_session(
        db_session, user, "nearly-expired",
        datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    live = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    live.cookies.set(auth_service.SESSION_COOKIE, "nearly-expired")
    try:
        assert (await live.get("/api/hats")).status_code == 200
    finally:
        await live.aclose()


async def test_prune_removes_only_expired_sessions(client, db_session):
    now = datetime.now(timezone.utc)
    user = await _owner(db_session)
    await _add_session(db_session, user, "gone-a", now - timedelta(days=40))
    await _add_session(db_session, user, "gone-b", now - timedelta(seconds=5))
    await _add_session(db_session, user, "kept", now + timedelta(days=3))

    removed = await auth_service.prune_expired_sessions(db_session)

    assert removed == 2
    remaining = await _session_ids(db_session)
    assert {"gone-a", "gone-b"}.isdisjoint(remaining)
    assert "kept" in remaining
    # The fixture's own session (a day out) survives too.
    assert len(remaining) == 2


async def test_an_expired_share_link_stops_resolving(db_session):
    """The same stored-UTC comparison on the other credential with an expiry.

    `resolve_token` compares the loaded `expires_at` with an aware `now()`;
    both sides of the boundary are pinned so a guard that never fires, or one
    that fires early, shows up.
    """
    from headroom.models.user import ShareLink
    from headroom.services import share_link_service

    now = datetime.now(timezone.utc)
    db_session.add_all([
        ShareLink(token="past", label="old", expires_at=now - timedelta(seconds=5)),
        ShareLink(token="future", label="new", expires_at=now + timedelta(days=1)),
    ])
    await db_session.commit()
    db_session.expire_all()  # read back from SQLite, which stores no zone

    with pytest.raises(share_link_service.ShareLinkInvalid):
        await share_link_service.resolve_token(db_session, "past")
    assert (await share_link_service.resolve_token(db_session, "future")).token == "future"


# ------------------------------- TTL ---------------------------------- #


async def test_a_login_session_lasts_thirty_days_in_the_row_and_the_cookie(anon_client, db_session):
    """30 days, as documented — and the cookie and the row agree on it.

    Asserted against the literal 30, not `SESSION_TTL_DAYS`: a test that reads
    the constant it is checking passes for any value of it.
    """
    creds = {"username": "ttl-owner", "password": "a-strong-password"}
    assert (await anon_client.post("/api/auth/setup", json=creds)).status_code == 200
    anon_client.cookies.clear()

    before = datetime.now(timezone.utc)
    resp = await anon_client.post("/api/auth/login", json=creds)
    assert resp.status_code == 200, resp.text

    cookie = next(
        h for h in resp.headers.get_list("set-cookie")
        if h.startswith(f"{auth_service.SESSION_COOKIE}=")
    )
    assert f"Max-Age={30 * 24 * 3600}" in cookie, cookie

    sid = cookie.split("=", 1)[1].split(";", 1)[0]
    db_session.expire_all()
    row = await db_session.get(AuthSession, sid)
    assert row is not None
    expected = before + timedelta(days=30)
    assert abs((row.expires_at - expected).total_seconds()) < 60, row.expires_at


# ----------------------------- lockout -------------------------------- #


class _Clock:
    """Stands in for the `time` module inside `auth_service` only.

    Patched on the module attribute rather than `time.monotonic` itself, which
    the event loop also reads.
    """

    def __init__(self) -> None:
        self.now = 1_000.0

    def monotonic(self) -> float:
        return self.now


async def test_a_lockout_lasts_fifteen_minutes(monkeypatch):
    """Five failures lock the (address, name) pair for fifteen minutes.

    Checked from both sides of the boundary: still locked a second before
    fifteen minutes have passed, free a second after.
    """
    clock = _Clock()
    monkeypatch.setattr(auth_service, "time", clock)

    for _ in range(5):
        assert not auth_service.is_rate_limited("10.0.0.9", "owner")
        auth_service.record_failure("10.0.0.9", "owner")
    assert auth_service.is_rate_limited("10.0.0.9", "owner")

    clock.now += 15 * 60 - 1
    assert auth_service.is_rate_limited("10.0.0.9", "owner"), "released early"

    clock.now += 2
    assert not auth_service.is_rate_limited("10.0.0.9", "owner"), "never released"


async def test_the_address_bucket_locks_every_name_after_twenty_failures(monkeypatch):
    """The second bucket OPERATIONS §6 documents: twenty failures from one
    address, across any usernames, lock that address for every name —
    including one it never tried — for the same fifteen minutes."""
    clock = _Clock()
    monkeypatch.setattr(auth_service, "time", clock)

    for i in range(20):
        assert not auth_service.is_rate_limited("10.0.0.7", f"name{i}")
        auth_service.record_failure("10.0.0.7", f"name{i}")
    assert auth_service.is_rate_limited("10.0.0.7", "never-tried")
    assert not auth_service.is_rate_limited("10.0.0.8", "never-tried"), (
        "another address must be unaffected"
    )

    clock.now += 15 * 60 + 1
    assert not auth_service.is_rate_limited("10.0.0.7", "never-tried")


# ------------------------- argon2 concurrency ------------------------- #


async def test_the_argon2_bound_works_on_a_second_event_loop():
    """The argon2 semaphore was module-level and bound to the first loop that
    made it wait; the next loop to contend it raised "bound to a different
    event loop" — on a login. It comes from `locks.loop_semaphore` now."""

    async def contend() -> None:
        # Three hashes against a bound of two: the third has to wait on the
        # semaphore, which is what binds it to the loop.
        await asyncio.gather(*(auth_service.hash_password_async("pw") for _ in range(3)))

    await contend()
    # A second loop, on a worker thread so it cannot disturb this one.
    await asyncio.to_thread(asyncio.run, contend())
