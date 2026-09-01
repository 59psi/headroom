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
from headroom.services import analysis_queue, import_service, settings_service
from headroom.utils import disk

router = APIRouter()


@router.get("/health")
async def health():
    """Liveness — always returns 200 if the process is reachable."""
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(request: Request, db: AsyncSession = Depends(get_db)):
    """Readiness — DB, uploads dir, free space, workers, and the API key.

    Returns 200 only if the DB is reachable, uploads/ is writable, there is
    room left on the volume, and every worker this deployment expects to be
    running still is. API-key presence is reported but does NOT cause a
    non-ready response (the app is intentionally usable without one).

    The last two gates are what make the Docker healthcheck worth having: it
    is the only automated observer this system has, and it previously could
    not fail for a full disk or a dead background worker — the two conditions
    most likely to develop over weeks of unattended running.

    This endpoint is unauthenticated (the Docker healthcheck polls it), so for
    anonymous callers it returns booleans ONLY — no raw exception strings, no
    filesystem paths, no API-key source. Authenticated callers see full detail
    plus the import-worker liveness canary. (S2/R9 — docs/AUDIT-HISTORY.md)
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

    # 3. Room to keep going. The probe above writes two bytes, and two bytes
    # fit on a volume with 8 KB free — while the next backup tarball does not,
    # SQLite starts raising `disk I/O error`, and uploads stop. Writable and
    # not-full are different questions.
    space = disk.check(upload_dir)
    if not space.ok:
        overall_ok = False

    # 4. Are the background workers actually running? Until this existed the
    # container could not report unhealthy because the analysis or import
    # worker had died — the two failures most likely across weeks of
    # unattended running. Gated on `worker_expected()` so a worker switched
    # off on purpose is not reported as a fault.
    #
    # **This reports; it does not recover, and the comment here used to claim
    # otherwise.** It said `restart: unless-stopped` acts on this. It does
    # not: Docker restart policies fire when the container *exits*, never when
    # a healthcheck goes `unhealthy`, so for as long as the process stays up
    # with a dead worker inside it, nothing in the base compose responds. The
    # signal was real and had no consumer — see `docker-compose.autoheal.yml`
    # and docs/OPERATIONS.md §7 for the two ways to give it one.
    workers_ok = not (
        (import_service.worker_expected() and not import_service.worker_alive())
        or (analysis_queue.worker_expected() and not analysis_queue.worker_alive())
    )
    if not workers_ok:
        overall_ok = False

    # 5. API key (informational — not a readiness gate)
    api_key, source = await settings_service.get_anthropic_key(db)

    # Detailed view only for an authenticated caller; anonymous callers (incl.
    # the container healthcheck) get booleans, enough to gate readiness.
    from headroom.auth import resolve_user

    authed = (await resolve_user(request)) is not None
    if authed:
        checks: dict[str, dict] = {
            "database": {"ok": db_ok, **({"error": db_err} if db_err else {})},
            "uploads_writable": {
                "ok": up_ok, "path": str(upload_dir),
                **({"error": up_err} if up_err else {}),
            },
            "anthropic_key": {"ok": True, "configured": bool(api_key), "source": source},
            "disk": {
                "ok": space.ok,
                "low": space.low,
                "free_bytes": space.free_bytes,
                "total_bytes": space.total_bytes,
                "free_pct": space.free_pct,
                "min_free_mb": disk.min_free_mb(),
                **({"error": space.error} if space.error else {}),
            },
            "import_worker": {
                "ok": import_service.worker_alive(),
                "expected": import_service.worker_expected(),
            },
            # Depth alongside liveness: a live worker with a growing backlog is
            # a different problem from a dead one, and both show up to a user as
            # "my hat says Analyzing…". Authenticated-only, like import_worker —
            # queue depth is operational detail.
            "analysis_worker": {
                "ok": analysis_queue.worker_alive(),
                "expected": analysis_queue.worker_expected(),
                "queued": analysis_queue.queue_depth(),
            },
        }
    else:
        # Booleans only. `disk` and `workers` are here because they GATE
        # readiness and an anonymous 503 with no reason is a worse artifact
        # than one that names which check failed — but "the disk is low" and
        # "a worker is down" carry no filesystem path, no capacity figure and
        # no queue depth, which is where the operational detail actually is.
        checks = {
            "database": {"ok": db_ok},
            "uploads_writable": {"ok": up_ok},
            "disk": {"ok": space.ok, "low": space.low},
            "workers": {"ok": workers_ok},
            "anthropic_key": {"ok": True, "configured": bool(api_key)},
        }

    body = {"ok": overall_ok, "checks": checks}
    code = status.HTTP_200_OK if overall_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(body, status_code=code)
