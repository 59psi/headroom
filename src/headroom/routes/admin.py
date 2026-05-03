"""Admin endpoints — recent analysis errors + backup download/list.

All gated by `require_admin`. With `HEADROOM_ADMIN_TOKEN` unset the dep is
a no-op (single-user-LAN default); set it and clients must present a Bearer
token.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.auth import require_admin
from headroom.database import get_db
from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.schemas.settings import BackupInfo, RecentError
from headroom.services import backup_service

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/recent-errors", response_model=list[RecentError])
async def recent_errors(limit: int = 20, db: AsyncSession = Depends(get_db)):
    """Most recent hats with analysis_status='error', newest first."""
    result = await db.execute(
        select(Hat)
        .where(Hat.analysis_status == "error")
        .order_by(Hat.analyzed_at.desc().nulls_last(), Hat.id.desc())
        .limit(max(1, min(limit, 100)))
    )
    rows = result.scalars().all()
    return [
        RecentError(
            hat_id=h.id,
            display_id=_safe_display_id(h),
            analysis_error=h.analysis_error,
            analyzed_at=cast(datetime | None, h.analyzed_at),
            photo_path=h.photo_path,
        )
        for h in rows
    ]


def _safe_display_id(hat: Hat) -> str | None:
    """display_id depends on hat.case being loaded; tolerate missing relationship."""
    try:
        return hat.display_id
    except Exception:  # noqa: BLE001
        return None


@router.get("/recent-errors/count")
async def recent_errors_count(db: AsyncSession = Depends(get_db)):
    """Cheap count for nav-badge display."""
    from sqlalchemy import func

    result = await db.execute(
        select(func.count(Hat.id)).where(Hat.analysis_status == "error")
    )
    return {"count": int(result.scalar() or 0)}


# --- Backups ----------------------------------------------------------- #


@router.get("/backup")
async def download_backup(
    include_uploads: bool = Query(True, description="Include uploads/ tree (photos)"),
):
    """Stream a one-shot tar.gz of /data.

    `include_uploads=false` returns a DB-only snapshot — much smaller and
    much faster when the photo tree is large.
    """
    filename = backup_service.streaming_filename(include_uploads=include_uploads)
    return StreamingResponse(
        backup_service.stream_backup(include_uploads=include_uploads),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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


# Need this here to fix a forward-ref: hat_service uses Case; importing it
# in module scope keeps the relationship loadable without round-trips.
_ = Case
