"""On-demand backup download + scheduled-backup inventory."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.admin import BackupHealthRead, BackupInfo
from headroom.services import activity_service, backup_service

router = APIRouter()


@router.get("/backup")
async def download_backup(
    include_uploads: bool = Query(True, description="Include uploads/ tree (photos)"),
    db: AsyncSession = Depends(get_db),
):
    """Stream a one-shot tar.gz of /data.

    `include_uploads=false` returns a DB-only snapshot — much smaller and
    much faster when the photo tree is large.
    """
    filename = backup_service.streaming_filename(include_uploads=include_uploads)
    # The backup tarball contains the whole DB (plaintext keys, tokens, session
    # ids, password hashes) — the single highest-value exfil artifact. Audit the
    # download so a full-dataset export is never invisible (S4/S10).
    await activity_service.log_activity(
        db, kind="backup.download", entity_type="system", entity_id=None,
        summary=f"Backup downloaded ({'full' if include_uploads else 'db-only'}): {filename}",
    )
    await db.commit()
    return StreamingResponse(
        backup_service.stream_backup(include_uploads=include_uploads),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/backups/health", response_model=BackupHealthRead)
async def scheduled_backup_health(request: Request):
    """Is the scheduler working — not merely, is there a file on disk.

    Registered before `/backups/{...}`-shaped paths would matter, and distinct
    from the inventory endpoint on purpose: the inventory answers "what do I
    have", this answers "will I get another one".
    """
    h = backup_service.health()
    task = getattr(request.app.state, "backup_task", None)
    return BackupHealthRead(
        enabled=backup_service.backup_enabled(),
        # A cancelled/finished task means no further backups will be written,
        # whatever the last attempt's outcome was.
        running=task is not None and not task.done(),
        last_attempt_at=h.last_attempt_at,
        last_success_at=h.last_success_at,
        last_error=h.last_error,
        consecutive_failures=h.consecutive_failures,
    )


@router.get("/backups", response_model=list[BackupInfo])
async def list_scheduled_backups():
    """Inventory of on-disk scheduled backups, newest first."""
    paths = await backup_service.list_backups()
    return [
        BackupInfo(
            filename=p.name,
            size_bytes=p.stat().st_size,
            created_at=datetime.fromtimestamp(p.stat().st_mtime),
        )
        for p in paths
    ]
