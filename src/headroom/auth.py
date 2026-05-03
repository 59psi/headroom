"""Optional admin-token guard for sensitive routes.

If `HEADROOM_ADMIN_TOKEN` is unset, `require_admin` is a no-op — preserves
the single-user-on-LAN ergonomics. If set, requests to guarded routes must
present `Authorization: Bearer <token>` and the token must match exactly
(constant-time compare). A startup warning is emitted when the token is
unset; see `app.py:lifespan`.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from headroom.config import settings


async def require_admin(authorization: str | None = Header(default=None)) -> None:
    expected = settings.admin_token
    if not expected:
        return  # Open mode — operator chose not to set a token.

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    presented = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token"
        )
