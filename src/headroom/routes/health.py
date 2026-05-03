"""Health endpoints.

`/health` is a quick liveness check (the process is up).
`/health/ready` is a readiness probe — DB reachable, uploads writable, key
configured. Use this from container orchestrators or external monitoring.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings
from headroom.database import get_db
from headroom.services import settings_service

router = APIRouter()


@router.get("/health")
async def health():
    """Liveness — always returns 200 if the process is reachable."""
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(db: AsyncSession = Depends(get_db)):
    """Readiness — verifies DB, uploads dir, and (informationally) the API key.

    Returns 200 only if DB is reachable and uploads/ is writable. API-key
    presence is reported but does NOT cause a non-ready response (the app is
    intentionally usable without one).
    """
    checks: dict[str, dict] = {}
    overall_ok = True

    # 1. DB reachable
    try:
        result = await db.execute(text("SELECT 1"))
        result.scalar()
        checks["database"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001 — surfaced via JSON
        checks["database"] = {"ok": False, "error": str(exc)}
        overall_ok = False

    # 2. Uploads dir writable
    upload_dir = settings.upload_dir
    try:
        probe = upload_dir / ".readiness_probe"
        probe.write_text("ok")
        probe.unlink(missing_ok=True)
        checks["uploads_writable"] = {"ok": True, "path": str(upload_dir)}
    except Exception as exc:  # noqa: BLE001
        checks["uploads_writable"] = {"ok": False, "path": str(upload_dir), "error": str(exc)}
        overall_ok = False

    # 3. API key (informational — not a readiness gate)
    api_key, source = await settings_service.get_anthropic_key(db)
    checks["anthropic_key"] = {
        "ok": True,
        "configured": bool(api_key),
        "source": source,
    }

    body = {"ok": overall_ok, "checks": checks}
    code = status.HTTP_200_OK if overall_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(body, status_code=code)
