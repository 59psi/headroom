"""Authentication: argon2 passwords, DB-backed sessions, login rate limiting.

Sessions are opaque 256-bit tokens stored server-side (revocable, no JWT
machinery). The cookie is httpOnly + SameSite=Lax; `secure` is set when the
request arrived over HTTPS (uvicorn runs with --proxy-headers in Docker so
Caddy's X-Forwarded-Proto is honored).

Rate limiting is in-memory per (client-ip, username) — the app is a single
process, so no shared store is needed.
"""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.user import AuthSession, User

SESSION_COOKIE = "headroom_session"
SESSION_TTL_DAYS = 30

_hasher = PasswordHasher()

# --------------------------- rate limiting ---------------------------- #

_MAX_FAILURES = 5
_LOCKOUT_SECONDS = 15 * 60
_failures: dict[str, list[float]] = {}


def _prune(key: str, now: float) -> list[float]:
    kept = [t for t in _failures.get(key, []) if now - t < _LOCKOUT_SECONDS]
    _failures[key] = kept
    return kept


def check_rate_limit(client_ip: str, username: str) -> None:
    key = f"{client_ip}:{username.lower()}"
    if len(_prune(key, time.monotonic())) >= _MAX_FAILURES:
        raise HTTPException(
            status_code=429,
            detail="Too many failed logins — try again in a few minutes.",
        )


def record_failure(client_ip: str, username: str) -> None:
    key = f"{client_ip}:{username.lower()}"
    _prune(key, time.monotonic())
    _failures.setdefault(key, []).append(time.monotonic())


def clear_failures(client_ip: str, username: str) -> None:
    _failures.pop(f"{client_ip}:{username.lower()}", None)


# ------------------------------ passwords ----------------------------- #


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:  # malformed hash — treat as auth failure, not a 500
        return False


# ------------------------------- users -------------------------------- #


def new_api_token() -> str:
    return f"hr_{secrets.token_urlsafe(32)}"


async def user_count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count(User.id)))).scalar_one()


async def create_user(db: AsyncSession, username: str, password: str) -> User:
    user = User(
        username=username.strip().lower(),
        password_hash=hash_password(password),
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


async def destroy_all_sessions(db: AsyncSession, user_id: int) -> None:
    await db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    await db.commit()
