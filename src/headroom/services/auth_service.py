"""Authentication: argon2 passwords, DB-backed sessions, login rate limiting.

Sessions are opaque 256-bit tokens stored server-side (revocable, no JWT
machinery). The cookie is httpOnly + SameSite=Lax; `secure` is set when the
request arrived over HTTPS (uvicorn runs with --proxy-headers in Docker so
Caddy's X-Forwarded-Proto is honored).

Rate limiting is in-memory per (client-ip, username) — the app is a single
process, so no shared store is needed.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.user import AuthSession, User

logger = logging.getLogger(__name__)

SESSION_COOKIE = "headroom_session"
SESSION_TTL_DAYS = 30

_hasher = PasswordHasher()

# --------------------------- rate limiting ---------------------------- #

_MAX_FAILURES = 5
_LOCKOUT_SECONDS = 15 * 60
_failures: dict[str, list[float]] = {}

#: Sweep every key this often (in calls), not on every call — see `_prune`.
_SWEEP_EVERY = 64
_since_sweep = 0

#: Keys already audited as blocked in the current window — see
#: `should_log_block`. Bounded, because it is fed by an open endpoint.
_blocked_logged: dict[str, float] = {}
_MAX_TRACKED_KEYS = 4096


def _prune(key: str, now: float) -> list[float]:
    """Expire `key`'s window, and periodically sweep every other key too.

    The per-key half was here from the start and its comment claimed to be an
    "unbounded-memory guard". It is not: it only ever touches the ONE key it
    is handed, so a client rotating the username — which is what credential
    stuffing looks like — leaves one permanent entry per name it tried, and
    nothing ever visits them again. Measured: 200 distinct usernames left 200
    live keys, still 200 after touching an unrelated key.

    The sweep is amortized on a counter rather than run every call, because
    the common case is a handful of keys and walking the dict on each login
    would be the wrong trade in the other direction.
    """
    kept = [t for t in _failures.get(key, []) if now - t < _LOCKOUT_SECONDS]
    if kept:
        _failures[key] = kept
    else:
        _failures.pop(key, None)

    global _since_sweep
    _since_sweep += 1
    if _since_sweep >= _SWEEP_EVERY:
        _since_sweep = 0
        for stale in [
            k for k, times in _failures.items()
            if not any(now - t < _LOCKOUT_SECONDS for t in times)
        ]:
            _failures.pop(stale, None)
    return kept


def is_rate_limited(client_ip: str, username: str) -> bool:
    key = f"{client_ip}:{username.lower()}"
    return len(_prune(key, time.monotonic())) >= _MAX_FAILURES



def record_failure(client_ip: str, username: str) -> None:
    key = f"{client_ip}:{username.lower()}"
    _prune(key, time.monotonic())
    _failures.setdefault(key, []).append(time.monotonic())


def clear_failures(client_ip: str, username: str) -> None:
    key = f"{client_ip}:{username.lower()}"
    _failures.pop(key, None)
    _blocked_logged.pop(key, None)


def should_log_block(client_ip: str, username: str) -> bool:
    """True only the FIRST time a given (ip, username) is blocked in a window.

    The 429 branch writes an `auth.login_blocked` activity row and commits it
    before raising, so the limiter was not stopping the write — it was only
    changing which row got written. One durable row per request, from an
    unauthenticated endpoint, retained 90 days: an anonymous client on the LAN
    could fill the SD card, which is the failure `/health/ready`'s disk floor
    exists to notice and this app would have caused itself.

    Once per lockout window keeps the security signal — "this address is being
    hammered" is answered by one row plus the log line every attempt still
    emits — while making the row count independent of the attempt count.
    """
    key = f"{client_ip}:{username.lower()}"
    now = time.monotonic()
    last = _blocked_logged.get(key)
    if last is not None and now - last < _LOCKOUT_SECONDS:
        return False
    _blocked_logged[key] = now
    if len(_blocked_logged) > _MAX_TRACKED_KEYS:
        # Age-based sweep first: expired entries are the ones nobody wants.
        for stale in [
            k for k, t in _blocked_logged.items() if now - t >= _LOCKOUT_SECONDS
        ]:
            _blocked_logged.pop(stale, None)
        # Then a HARD cap, which is what makes the name true. The sweep above
        # was the whole mechanism, and it only removes entries old enough to
        # have expired — so a burst that fills this faster than `_LOCKOUT_SECONDS`
        # elapses removes nothing at all and the dict grows without limit.
        # Measured before this line existed: 10,000 keys survived a "bound" of
        # 4,096. It is fed by an unauthenticated endpoint, so the eviction has
        # to be unconditional, not best-effort.
        #
        # Oldest-first, so what is dropped is the least recently blocked — the
        # entries whose absence costs at most one extra audit line.
        if len(_blocked_logged) > _MAX_TRACKED_KEYS:
            for stale, _t in sorted(_blocked_logged.items(), key=lambda kv: kv[1])[
                : len(_blocked_logged) - _MAX_TRACKED_KEYS
            ]:
                _blocked_logged.pop(stale, None)
    return True


# ------------------------------ passwords ----------------------------- #


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:  # noqa: BLE001 — malformed hash is an auth failure, not a 500
        return False


# argon2id is 64 MiB + ~0.3-1 s on a Pi. Running it inline on the single event
# loop freezes every in-flight request per attempt and lets a login flood pin
# memory. Offload to a thread, bounded so concurrent attempts can't stack N×64
# MiB. Bound of 2 keeps interactive logins snappy without a memory spike.
_ARGON2_MAX_CONCURRENCY = 2
_argon2_semaphore = asyncio.Semaphore(_ARGON2_MAX_CONCURRENCY)


async def verify_password_async(password_hash: str, password: str) -> bool:
    async with _argon2_semaphore:
        return await asyncio.to_thread(verify_password, password_hash, password)


async def hash_password_async(password: str) -> str:
    async with _argon2_semaphore:
        return await asyncio.to_thread(hash_password, password)


# ------------------------------- users -------------------------------- #


def new_api_token() -> str:
    return f"hr_{secrets.token_urlsafe(32)}"


async def user_count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count(User.id)))).scalar_one()


async def create_user(db: AsyncSession, username: str, password: str) -> User:
    # Hashed OFF the event loop, like every other argon2 call here. This was
    # the one site still using the sync form: argon2id at these parameters is
    # ~64 MiB and a few hundred milliseconds on a Pi, and on the event loop
    # that is the whole process frozen — including the health check. Only
    # first-run setup reaches it, which is exactly why it went unnoticed.
    user = User(
        username=username.strip().lower(),
        password_hash=await hash_password_async(password),
        api_token=new_api_token(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(
        select(User).where(User.username == username.strip().lower())
    )
    return result.scalar_one_or_none()


async def get_user_by_api_token(db: AsyncSession, token: str) -> User | None:
    result = await db.execute(select(User).where(User.api_token == token))
    return result.scalar_one_or_none()


# ------------------------------ sessions ------------------------------ #


async def create_session(db: AsyncSession, user: User) -> AuthSession:
    session = AuthSession(
        id=secrets.token_urlsafe(32),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS),
    )
    db.add(session)
    await db.commit()
    return session


async def get_session_user(db: AsyncSession, session_id: str) -> User | None:
    result = await db.execute(select(AuthSession).where(AuthSession.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        return None
    expires = session.expires_at
    if expires.tzinfo is None:  # SQLite returns naive datetimes
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        await db.delete(session)
        await db.commit()
        return None
    return session.user


async def destroy_session(db: AsyncSession, session_id: str) -> None:
    await db.execute(delete(AuthSession).where(AuthSession.id == session_id))
    await db.commit()



async def destroy_other_sessions(db: AsyncSession, user_id: int, keep: str | None) -> None:
    """Revoke every session for a user except `keep` (the current one)."""
    stmt = delete(AuthSession).where(AuthSession.user_id == user_id)
    if keep:
        stmt = stmt.where(AuthSession.id != keep)
    await db.execute(stmt)
    await db.commit()


async def prune_expired_sessions(db: AsyncSession) -> int:
    """Delete auth_sessions whose expiry has passed. Returns rows removed.

    Expiry was previously enforced only lazily, when that exact cookie was
    presented again — so a session abandoned by closing a browser, clearing
    cookies, or replacing a phone was never collected at all. Nothing ever
    revisits those rows, so the table only grew. They are also credentials:
    keeping expired ones is keeping authentication material that no longer has
    any purpose.
    """
    result = await db.execute(
        delete(AuthSession).where(AuthSession.expires_at < datetime.now(timezone.utc))
    )
    await db.commit()
    removed = result.rowcount or 0
    if removed:
        logger.info("Pruned %d expired auth session(s)", removed)
    return removed
