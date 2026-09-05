"""Auth endpoints: first-run setup, login/logout, API token, passkeys.

Everything under /api/auth/ is exempt from the gate middleware; each
endpoint enforces its own requirements. Passwords never leave this module
unhashed; the API token is only readable by an authenticated session.
"""

from __future__ import annotations

import logging
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.auth import client_ip, require_user
from headroom.database import get_db
from headroom.models.app_setting import AppSetting
from headroom.models.user import PasskeyCredential, User
from headroom.services import auth_service, passkey_service
from headroom.services.activity_service import log_activity
from headroom.schemas.auth import (
    AuthStatus,
    Credentials,
    PasskeyLoginVerify,
    PasskeyRegisterVerify,
    PasswordChange,
    PasswordConfirm,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


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




@router.get("/status", response_model=AuthStatus)
async def auth_status(request: Request, db: AsyncSession = Depends(get_db)):
    from headroom.auth import resolve_user

    needs_setup = (await auth_service.user_count(db)) == 0
    user = None if needs_setup else await resolve_user(request)
    from headroom.services import guest_view_service

    return AuthStatus(
        needs_setup=needs_setup,
        authenticated=user is not None,
        username=user.username if user else None,
        # None, not False — see the field's note. The model serializer then
        # drops it from the payload entirely.
        guest_view_enabled=(
            True if await guest_view_service.is_enabled(db) else None
        ),
    )


@router.post("/setup", response_model=AuthStatus)
async def first_run_setup(
    data: Credentials, request: Request, response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Create the owner account. Only available while no users exist.

    `HEADROOM_SETUP_TOKEN` closes the land-grab window when it is set. Until
    the owner completes setup this endpoint hands full control to whoever posts
    to it first, and `GET /api/auth/status` publishes `needs_setup: true`, so
    the window is not merely open — it is advertised. On a LAN that is nearly
    theoretical; on the Let's Encrypt overlay the hostname is in a public
    certificate-transparency log within seconds of issuance, so "whoever
    reaches it first" includes anyone watching CT.

    Opt-in rather than always-on, and that is the deliberate choice: a required
    token would put a mandatory step between a fresh `docker compose up` and a
    working app for the LAN install that is the primary deployment, to defend
    against an attacker who is already on the LAN. Set it for an
    internet-facing deployment; leave it unset and behavior is unchanged.
    """
    expected = os.environ.get("HEADROOM_SETUP_TOKEN", "").strip()
    if expected and not secrets.compare_digest(data.setup_token or "", expected):
        # Deliberately indistinguishable from "setup already completed": an
        # attacker learning that the token is merely WRONG has learned the box
        # is unclaimed and worth coming back to.
        logger.warning("Rejected /api/auth/setup: HEADROOM_SETUP_TOKEN mismatch")
        raise HTTPException(status_code=403, detail="Setup already completed")
    if await auth_service.user_count(db) > 0:
        # `from None`, not `from exc`: an auth response must not carry the
        # database error that produced it, and here the IntegrityError is
        # expected — it IS the concurrency guard working.
        raise HTTPException(status_code=403, detail="Setup already completed") from None
    # Serialize first-run setup against a racing second POST: app_settings.key
    # is a PRIMARY KEY, so only one concurrent transaction can claim this
    # sentinel — the loser's INSERT collides and rolls back its owner account
    # too, instead of both check-then-inserting two co-equal owners (S5/R10 — docs/AUDIT-HISTORY.md).
    db.add(AppSetting(key="owner_setup_done", value="1"))
    try:
        user = await auth_service.create_user(db, data.username, data.password)
    except IntegrityError:
        await db.rollback()
        # `from None`, not `from exc`: an auth response must not carry the
        # database error that produced it, and here the IntegrityError is
        # expected — it IS the concurrency guard doing its job.
        raise HTTPException(
            status_code=403, detail="Setup already completed"
        ) from None
    session = await auth_service.create_session(db, user)
    _set_session_cookie(response, request, session.id)
    await log_activity(
        db, kind="auth.setup", entity_type="user", entity_id=user.id,
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
    ip = client_ip(request)
    if auth_service.is_rate_limited(ip, data.username):
        # The log line goes out every time — it is free and it is what you
        # grep. The durable audit ROW goes out once per lockout window: this
        # endpoint is unauthenticated, so a row per request let anyone fill
        # the disk, 90 days at a time. See `auth_service.should_log_block`.
        logger.warning("Login rate-limited: '%s' from %s", data.username, ip)
        if auth_service.should_log_block(ip, data.username):
            await log_activity(
                db, kind="auth.login_blocked", entity_type="auth", entity_id=None,
                summary=f"Login blocked (rate limit): '{data.username}' from {ip}",
                details={"ip": ip, "username": data.username},
            )
            await db.commit()
        raise HTTPException(
            status_code=429,
            detail="Too many failed logins — try again in a few minutes.",
        )
    user = await auth_service.get_user_by_username(db, data.username)
    if user is None or not await auth_service.verify_password_async(
        user.password_hash, data.password
    ):
        auth_service.record_failure(ip, data.username)
        logger.warning("Login failed: '%s' from %s", data.username, ip)
        await log_activity(
            db, kind="auth.login_failed", entity_type="auth",
            entity_id=user.id if user else None,
            summary=f"Failed login: '{data.username}' from {ip}",
            details={"ip": ip, "username": data.username},
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")
    auth_service.clear_failures(ip, data.username)
    session = await auth_service.create_session(db, user)
    _set_session_cookie(response, request, session.id)
    logger.info("Login success: '%s' from %s", user.username, ip)
    await log_activity(
        db, kind="auth.login", entity_type="user", entity_id=user.id,
        summary=f"Login: '{user.username}' from {ip}", details={"ip": ip},
    )
    await db.commit()
    return AuthStatus(needs_setup=False, authenticated=True, username=user.username)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    session_id = request.cookies.get(auth_service.SESSION_COOKIE)
    if session_id:
        await auth_service.destroy_session(db, session_id)
    response.delete_cookie(auth_service.SESSION_COOKIE, path="/")


@router.get("/me")
async def me(user: User = Depends(require_user)):
    """Profile. Deliberately NOT the bearer token.

    It used to return `api_token` on every call, which made a stolen session
    upgrade itself into a credential that outlives it: sessions can be revoked
    (logout, password change, `destroy_other_sessions`) and the token cannot be
    reached by any of them — the holder simply keeps full API access. The card
    that displays it fetches this on every Settings load, so the secret was on
    the wire far more often than the one moment somebody wanted to read it.

    `token_set` rather than the value: the card needs to know the field exists
    to render its controls, and that is not secret.
    """
    return {"username": user.username, "token_set": bool(user.api_token)}


@router.post("/token/reveal")
async def reveal_api_token(
    data: PasswordConfirm,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Show the existing token, on proof of the password.

    A POST because it is not cacheable and must not land in a URL, history
    entry or referrer — the same reason the Google Vision key stopped being a
    query parameter.
    """
    if not await auth_service.verify_password_async(
        user.password_hash, data.current_password
    ):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    await log_activity(
        db, kind="auth.token_revealed", entity_type="user", entity_id=user.id,
        summary=f"API token revealed for '{user.username}'",
    )
    await db.commit()
    return {"api_token": user.api_token}


@router.post("/token/rotate")
async def rotate_api_token(
    data: PasswordConfirm,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Mint a new token, on proof of the password.

    Gated for the same reason as reveal, and it is not enough to gate reveal
    alone: rotation RETURNS the new token, so an attacker holding only a
    session could mint themselves a fresh long-lived credential and read it
    back. Closing one door and leaving the other one open would have been
    security theater — the escalation path is identical.
    """
    if not await auth_service.verify_password_async(
        user.password_hash, data.current_password
    ):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    user.api_token = auth_service.new_api_token()
    db.add(user)
    await log_activity(
        db, kind="auth.token_rotated", entity_type="user", entity_id=user.id,
        summary=f"API token rotated for '{user.username}'",
    )
    await db.commit()
    return {"api_token": user.api_token}


@router.post("/password", status_code=204)
async def change_password(
    data: PasswordChange,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    if not await auth_service.verify_password_async(
        user.password_hash, data.current_password
    ):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    user.password_hash = await auth_service.hash_password_async(data.new_password)
    # Password change is a compromise response, so make it a COMPLETE one:
    # rotate the long-lived bearer token too, otherwise a stolen api_token
    # survives the reset (session revocation alone doesn't cover it — S3).
    user.api_token = auth_service.new_api_token()
    db.add(user)
    await db.commit()
    # Revoke every other session so a stolen cookie dies with the old password.
    # The session that made this request stays valid.
    await auth_service.destroy_other_sessions(
        db, user.id, keep=request.cookies.get(auth_service.SESSION_COOKIE)
    )
    await log_activity(
        db, kind="auth.password_change", entity_type="user", entity_id=user.id,
        summary=f"Password changed for '{user.username}' (token rotated, other sessions revoked)",
    )
    await db.commit()


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
        raise HTTPException(
            status_code=400, detail=f"Passkey verification failed: {exc}"
        ) from None
    db.add(
        PasskeyCredential(
            user_id=user.id,
            credential_id=verified["credential_id"],
            public_key=verified["public_key"],
            sign_count=verified["sign_count"],
            name=data.name[:80] or "Passkey",
        )
    )
    await log_activity(
        db, kind="auth.passkey_added", entity_type="user", entity_id=user.id,
        summary=f"Passkey '{data.name[:80] or 'Passkey'}' registered for '{user.username}'",
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
    await log_activity(
        db, kind="auth.passkey_removed", entity_type="user", entity_id=user.id,
        summary=f"Passkey '{row.name}' removed for '{user.username}'",
    )
    await db.commit()


@router.post("/passkeys/login/options")
async def passkey_login_options():
    state_id, options = passkey_service.authentication_options()
    return {"state_id": state_id, "options": options}


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
        raise HTTPException(
            status_code=401, detail=f"Passkey login failed: {exc}"
        ) from None
    stored.sign_count = new_count
    user = stored.user
    session = await auth_service.create_session(db, user)
    _set_session_cookie(response, request, session.id)
    logger.info("Passkey login success: '%s' from %s", user.username, client_ip(request))
    await log_activity(
        db, kind="auth.login", entity_type="user", entity_id=user.id,
        summary=f"Passkey login: '{user.username}' from {client_ip(request)}",
        details={"ip": client_ip(request), "method": "passkey"},
    )
    await db.commit()
    return AuthStatus(needs_setup=False, authenticated=True, username=user.username)
