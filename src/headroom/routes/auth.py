"""Auth endpoints: first-run setup, login/logout, API token, passkeys.

Everything under /api/auth/ is exempt from the gate middleware; each
endpoint enforces its own requirements. Passwords never leave this module
unhashed; the API token is only readable by an authenticated session.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.auth import require_user
from headroom.database import get_db
from headroom.models.user import PasskeyCredential, User
from headroom.services import auth_service, passkey_service
from headroom.services.activity_service import log_activity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=60)
    password: str = Field(min_length=8, max_length=200)


class AuthStatus(BaseModel):
    needs_setup: bool
    authenticated: bool
    username: str | None = None


def _set_session_cookie(response: Response, request: Request, session_id: str) -> None:
    response.set_cookie(
        auth_service.SESSION_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=auth_service.SESSION_TTL_DAYS * 24 * 3600,
        path="/",
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/status", response_model=AuthStatus)
async def auth_status(request: Request, db: AsyncSession = Depends(get_db)):
    from headroom.auth import _resolve_user

    needs_setup = (await auth_service.user_count(db)) == 0
    user = None if needs_setup else await _resolve_user(request)
    return AuthStatus(
        needs_setup=needs_setup,
        authenticated=user is not None,
        username=user.username if user else None,
    )


@router.post("/setup", response_model=AuthStatus)
async def first_run_setup(
    data: Credentials, request: Request, response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Create the owner account. Only available while no users exist."""
    if await auth_service.user_count(db) > 0:
        raise HTTPException(status_code=403, detail="Setup already completed")
    user = await auth_service.create_user(db, data.username, data.password)
    session = await auth_service.create_session(db, user)
    _set_session_cookie(response, request, session.id)
    await log_activity(
        db, kind="auth", entity_type="user", entity_id=user.id,
        summary=f"Owner account '{user.username}' created",
    )
    await db.commit()
    logger.info("Owner account created: %s", user.username)
    return AuthStatus(needs_setup=False, authenticated=True, username=user.username)


@router.post("/login", response_model=AuthStatus)
async def login(
    data: Credentials, request: Request, response: Response,
    db: AsyncSession = Depends(get_db),
):
    ip = _client_ip(request)
    auth_service.check_rate_limit(ip, data.username)
    user = await auth_service.get_user_by_username(db, data.username)
    if user is None or not auth_service.verify_password(user.password_hash, data.password):
        auth_service.record_failure(ip, data.username)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    auth_service.clear_failures(ip, data.username)
    session = await auth_service.create_session(db, user)
    _set_session_cookie(response, request, session.id)
    return AuthStatus(needs_setup=False, authenticated=True, username=user.username)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    session_id = request.cookies.get(auth_service.SESSION_COOKIE)
    if session_id:
        await auth_service.destroy_session(db, session_id)
    response.delete_cookie(auth_service.SESSION_COOKIE, path="/")


@router.get("/me")
async def me(user: User = Depends(require_user)):
    """Profile + the bearer token for cookie-less clients (iOS Shortcut)."""
    return {"username": user.username, "api_token": user.api_token}


@router.post("/token/rotate")
async def rotate_api_token(
    user: User = Depends(require_user), db: AsyncSession = Depends(get_db)
):
    user.api_token = auth_service.new_api_token()
    db.add(user)
    await db.commit()
    return {"api_token": user.api_token}


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


@router.post("/password", status_code=204)
async def change_password(
    data: PasswordChange,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    if not auth_service.verify_password(user.password_hash, data.current_password):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    user.password_hash = auth_service.hash_password(data.new_password)
    db.add(user)
    await db.commit()
    # Changing the password is often a compromise response: revoke every
    # other session so a stolen cookie dies with the old password. The
    # session that made this request stays valid.
    await auth_service.destroy_other_sessions(
        db, user.id, keep=request.cookies.get(auth_service.SESSION_COOKIE)
    )


# ------------------------------ passkeys ------------------------------ #


@router.get("/passkeys")
async def list_passkeys(
    user: User = Depends(require_user), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(PasskeyCredential).where(PasskeyCredential.user_id == user.id)
    )
    return [
        {"id": c.id, "name": c.name, "created_at": c.created_at}
        for c in result.scalars().all()
    ]


@router.post("/passkeys/register/options")
async def passkey_register_options(
    user: User = Depends(require_user), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(PasskeyCredential).where(PasskeyCredential.user_id == user.id)
    )
    state_id, options = passkey_service.registration_options(
        user, list(result.scalars().all())
    )
    return {"state_id": state_id, "options": options}


class PasskeyRegisterVerify(BaseModel):
    state_id: str
    credential: dict
    name: str = "Passkey"


@router.post("/passkeys/register/verify")
async def passkey_register_verify(
    data: PasskeyRegisterVerify,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    entry = passkey_service.pop_challenge(data.state_id)
    if entry is None or entry[1] != user.id:
        raise HTTPException(status_code=400, detail="Challenge expired — try again")
    try:
        verified = passkey_service.verify_registration(data.credential, entry[0])
    except Exception as exc:  # noqa: BLE001 — library raises many subtypes
        raise HTTPException(status_code=400, detail=f"Passkey verification failed: {exc}")
    db.add(
        PasskeyCredential(
            user_id=user.id,
            credential_id=verified["credential_id"],
            public_key=verified["public_key"],
            sign_count=verified["sign_count"],
            name=data.name[:80] or "Passkey",
        )
    )
    await db.commit()
    return {"ok": True}


@router.delete("/passkeys/{passkey_id}", status_code=204)
async def delete_passkey(
    passkey_id: int,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(PasskeyCredential, passkey_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Passkey not found")
    await db.delete(row)
    await db.commit()


@router.post("/passkeys/login/options")
async def passkey_login_options():
    state_id, options = passkey_service.authentication_options()
    return {"state_id": state_id, "options": options}


class PasskeyLoginVerify(BaseModel):
    state_id: str
    credential: dict


@router.post("/passkeys/login/verify", response_model=AuthStatus)
async def passkey_login_verify(
    data: PasskeyLoginVerify,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    entry = passkey_service.pop_challenge(data.state_id)
    if entry is None:
        raise HTTPException(status_code=400, detail="Challenge expired — try again")
    credential_id = data.credential.get("id", "")
    result = await db.execute(
        select(PasskeyCredential).where(
            PasskeyCredential.credential_id == credential_id
        )
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        raise HTTPException(status_code=401, detail="Unknown passkey")
    try:
        new_count = passkey_service.verify_authentication(
            data.credential, entry[0], stored
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail=f"Passkey login failed: {exc}")
    stored.sign_count = new_count
    user = stored.user
    session = await auth_service.create_session(db, user)
    _set_session_cookie(response, request, session.id)
    return AuthStatus(needs_setup=False, authenticated=True, username=user.username)
