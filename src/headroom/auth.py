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

import logging

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from headroom.models.user import User
from headroom.services import auth_service

logger = logging.getLogger(__name__)


def client_ip(request: Request) -> str:
    """Best-effort remote address.

    One definition: the login rate limiter and the middleware's 401 log both
    key off it, and a limiter that buckets by a different string than the log
    reports is a debugging trap.

    **On the plain bridge compose this may be the Docker gateway, not the
    caller** — and if it is, every LAN client shares one rate-limit bucket, so
    a stranger's failed logins can lock the owner out, and the IP on every
    `auth.login_failed` row identifies nothing. Whether it happens depends on
    the host's `userland-proxy` setting: with it on (the historical Linux
    default) the source is rewritten to the gateway; with iptables DNAT it is
    preserved. The app cannot tell which from inside the container.

    Not read from `X-Forwarded-For` here, deliberately. That header is
    attacker-controlled on any request that does not come through a proxy, and
    trusting it would let a caller pick its own rate-limit bucket — strictly
    worse than one shared bucket. uvicorn's `--forwarded-allow-ips` is the
    right place: it applies the header only from peers the operator has named,
    and the Dockerfile already restricts it to loopback for the Caddy overlays,
    which is why all three LAN-HTTPS paths report the real client. Documented
    in `docs/OPERATIONS.md §6`.
    """
    return request.client.host if request.client else "unknown"


# Prefixes that never require auth.
_OPEN_PREFIXES = (
    "/api/auth/",
    "/api/public/",
    "/health",
)

# Prefixes that carry collection data and therefore require auth.
#
# `/openapi.json`, `/docs` and `/redoc` are here because they are the one part
# of the app that describes the app, and they begin with none of the prefixes
# above — so a gate written as "everything under /api/" published 101 paths,
# every schema and every field name to any anonymous caller. On the LAN that is
# an oddity; on the Let's Encrypt overlay it is a complete map of the attack
# surface, handed out on request. It also sat directly against the posture of
# the rest of this module: `/health/ready` goes to deliberate trouble to redact
# filesystem paths and key sources from anonymous callers, while `/openapi.json`
# next door gave away the shape of everything.
_PROTECTED_PREFIXES = (
    "/api/", "/uploads/", "/openapi.json", "/docs", "/redoc",
)


async def resolve_user(request: Request) -> User | None:
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
    user = getattr(request.state, "user", None) or await resolve_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return user


# Back-compat alias: routes formerly guarded by the admin token now simply
# require a logged-in user (the middleware already enforces this; keeping
# the dependency is defense in depth).
require_admin = require_user


# Sent on every response. Values are deliberately conservative rather than
# maximal — this app serves its own SPA from its own origin and loads nothing
# from anywhere else, so a strict policy costs nothing and there is no CDN to
# grandfather in.
#
# That last claim was false for six releases. `tokens.css` pulled the four
# typefaces from Google Fonts, so `style-src 'self'` and `font-src 'self'`
# blocked the app's entire type system from 2.12.0 onward and everything
# rendered in system-ui. Nobody saw it: existing users had the fonts cached
# from before the header existed, a blocked font logs to the console and
# nowhere else, and text that is merely the wrong shape still reads fine.
# The fonts are now bundled (see `main.tsx`), which makes the comment true.
# Keep it true — if something here needs an external origin, self-host it
# instead of widening the policy.
_SECURITY_HEADERS = {
    # No external scripts, styles, fonts, frames or XHR targets. 'unsafe-inline'
    # for style-src only: the SPA sets inline `style=` attributes in several
    # components, and removing those is a much larger change than this header.
    # No 'unsafe-inline' for script-src, which is the one that actually matters
    # for XSS.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    # Redundant with frame-ancestors for modern browsers, kept for older ones.
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}


#: What a browser may keep, by what it is. Nothing set any of these:
#: `/assets/*` (content-hashed, immortal) got heuristic caching and a 304
#: round trip per file per visit; `/uploads/*` (gated photos) got heuristic
#: caching too, so after Sign out a plain fetch of a hat photo still answered
#: 200 from the cache on a shared device; `/api/*` JSON had no policy at all.
#: `no-cache` on uploads means "revalidate every time": the ETag makes that a
#: cheap 304 while signed in, and a 401 once signed out — the photo is never
#: served from cache without the server's say-so.
_CACHE_POLICY = (
    ("/assets/", "public, max-age=31536000, immutable"),
    ("/uploads/", "private, no-cache"),
    ("/api/", "no-store"),
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach standard hardening headers — and the caching policy — to every response.

    Deliberately does NOT set HSTS. The primary deployment is `http://` on a
    LAN, and an HSTS header served once would pin that hostname to HTTPS in the
    browser for its max-age — locking the owner out of their own app on a
    hostname they cannot easily un-pin. Caddy adds HSTS on the genuinely
    internet-facing overlay, which is where it belongs.

    `setdefault` throughout: a route that names its own policy (the public
    logo's five-minute `max-age`, the SPA shell's `no-cache, must-revalidate`)
    keeps it.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        path = request.url.path
        for prefix, policy in _CACHE_POLICY:
            if path.startswith(prefix):
                response.headers.setdefault("Cache-Control", policy)
                break
        return response


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
            user = await resolve_user(request)
            if user is None:
                # Logged because this is the only unauthenticated way to probe
                # the API, and it was previously silent: `POST /api/auth/login`
                # is rate-limited and audited, but sweeping bearer tokens
                # against any other endpoint produced no record at all. At
                # WARNING so a burst is visible in the same place every other
                # operational problem shows up, and without the token or cookie
                # value — logging a credential to diagnose credential abuse is
                # its own vulnerability.
                logger.warning(
                    "Rejected unauthenticated %s %s from %s",
                    request.method, path, client_ip(request),
                )
                return JSONResponse(
                    status_code=401, content={"detail": "Authentication required"}
                )
            request.state.user = user
        return await call_next(request)
