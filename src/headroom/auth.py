"""Session/token authentication guards and the app-wide gate middleware.

Everything data-bearing — /api/* and /uploads/* — requires either a valid
session cookie or a bearer API token (for cookie-less clients like the iOS
Shortcut). The SPA shell, its hashed assets, PWA manifest/icons, health
probes, the auth endpoints themselves, and /api/public/* (share links) stay
open: they contain no collection data.

The middleware resolves users through `request.app.state.session_factory`
so tests can point it at their own database.

This replaces the old optional HEADROOM_ADMIN_TOKEN guard — accounts are
mandatory now; the first visit creates the owner account via /api/auth/setup.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from headroom.models.user import User
from headroom.services import auth_service

# Prefixes that never require auth.
_OPEN_PREFIXES = (
    "/api/auth/",
    "/api/public/",
    "/health",
)

# Prefixes that carry collection data and therefore require auth.
_PROTECTED_PREFIXES = ("/api/", "/uploads/")


async def _resolve_user(request: Request) -> User | None:
    """Session cookie first, then bearer API token. None when anonymous."""
    session_factory = request.app.state.session_factory
    session_id = request.cookies.get(auth_service.SESSION_COOKIE)
    if session_id:
        async with session_factory() as db:
            user = await auth_service.get_session_user(db, session_id)
        if user is not None:
            return user
    authz = request.headers.get("authorization", "")
    if authz.lower().startswith("bearer "):
        token = authz.split(" ", 1)[1].strip()
        if token:
            async with session_factory() as db:
                return await auth_service.get_user_by_api_token(db, token)
    return None


async def require_user(request: Request) -> User:
    """Route dependency for handlers that need the acting user."""
    user = getattr(request.state, "user", None) or await _resolve_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return user


# Back-compat alias: routes formerly guarded by the admin token now simply
# require a logged-in user (the middleware already enforces this; keeping
# the dependency is defense in depth).
require_admin = require_user


class AuthGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        needs_auth = path.startswith(_PROTECTED_PREFIXES) and not path.startswith(
            _OPEN_PREFIXES
        )
        # The Web Share Target (Android PWA) posts photos to /share — that
        # mutates data and needs a session. GET /share/<token> is only the
        # public SPA shell for share links and stays open.
        if path == "/share" and request.method == "POST":
            needs_auth = True
        if needs_auth:
            user = await _resolve_user(request)
            if user is None:
                return JSONResponse(
                    status_code=401, content={"detail": "Authentication required"}
                )
            request.state.user = user
        return await call_next(request)
