"""Health endpoints.

`/health` is a quick liveness check (the process is up).
`/health/ready` is a readiness probe — DB reachable, uploads writable, key
configured. Use this from container orchestrators or external monitoring.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings
from headroom.database import get_db
from headroom.services import import_service, settings_service

router = APIRouter()


@router.get("/health")
async def health():
    """Liveness — always returns 200 if the process is reachable."""
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(request: Request, db: AsyncSession = Depends(get_db)):
    """Readiness — verifies DB, uploads dir, and (informationally) the API key.

    Returns 200 only if DB is reachable and uploads/ is writable. API-key
    presence is reported but does NOT cause a non-ready response (the app is
    intentionally usable without one).

    This endpoint is unauthenticated (the Docker healthcheck polls it), so for
    anonymous callers it returns booleans ONLY — no raw exception strings, no
    filesystem paths, no API-key source. Authenticated callers see full detail
    plus the import-worker liveness canary. (S2/R9)
    """
    overall_ok = True

    # 1. DB reachable
    db_ok, db_err = True, None
    try:
        (await db.execute(text("SELECT 1"))).scalar()
    except Exception as exc:  # noqa: BLE001 — surfaced via JSON to authed only
        db_ok, db_err = False, str(exc)
        overall_ok = False

    # 2. Uploads dir writable
    upload_dir = settings.upload_dir
    up_ok, up_err = True, None
    try:
        probe = upload_dir / ".readiness_probe"
        probe.write_text("ok")
        probe.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        up_ok, up_err = False, str(exc)
        overall_ok = False

    # 3. API key (informational — not a readiness gate)
    api_key, source = await settings_service.get_anthropic_key(db)

    # Detailed view only for an authenticated caller; anonymous callers (incl.
    # the container healthcheck) get booleans, enough to gate readiness.
    from headroom.auth import _resolve_user

    authed = (await _resolve_user(request)) is not None
    if authed:
        checks: dict[str, dict] = {
            "database": {"ok": db_ok, **({"error": db_err} if db_err else {})},
            "uploads_writable": {
                "ok": up_ok, "path": str(upload_dir),
                **({"error": up_err} if up_err else {}),
            },
            "anthropic_key": {"ok": True, "configured": bool(api_key), "source": source},
            "import_worker": {"ok": import_service.worker_alive()},
        }
    else:
        checks = {
            "database": {"ok": db_ok},
            "uploads_writable": {"ok": up_ok},
            "anthropic_key": {"ok": True, "configured": bool(api_key)},
        }

    body = {"ok": overall_ok, "checks": checks}
    code = status.HTTP_200_OK if overall_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(body, status_code=code)
