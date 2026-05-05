"""Admin endpoints — recent analysis errors + backup download/list.

All gated by `require_admin`. With `HEADROOM_ADMIN_TOKEN` unset the dep is
a no-op (single-user-LAN default); set it and clients must present a Bearer
token.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.auth import require_admin
from headroom.database import get_db
from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.schemas.settings import BackupInfo, RecentError
from headroom.services import (
    activity_service,
    backup_service,
    ebay_service,
    hat_service,
    report_service,
    settings_service,
)

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ---- v0.4 schemas (kept inline because they're admin-only and small) -- #


class EbayCredsStatus(BaseModel):
    configured: bool
    app_id_masked: str | None = None
    marketplace: str = "EBAY_US"
    detected_env: str | None = None  # "production" | "sandbox" | "unknown"


def _detect_ebay_env(app_id: str | None) -> str | None:
    """eBay App IDs follow `<user>-<app>-<env>-<r1>-<r2>`. The middle env
    segment is PRD (production) or SBX (sandbox). Detecting this lets us
    flag a sandbox key paste before the user even hits Test."""
    if not app_id:
        return None
    upper = app_id.upper()
    if "-PRD-" in upper:
        return "production"
    if "-SBX-" in upper:
        return "sandbox"
    return "unknown"


class EbayCredsUpdate(BaseModel):
    app_id: str = Field(min_length=4, max_length=120)
    cert_id: str = Field(min_length=4, max_length=200)
    marketplace: str = "EBAY_US"


class ActivityRow(BaseModel):
    id: int
    occurred_at: datetime
    kind: str
    entity_type: str
    entity_id: int | None
    summary: str
    details: str | None


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


# ---- Activity log ---------------------------------------------------- #


@router.get("/activity-log", response_model=list[ActivityRow])
async def list_activity_log(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    entity_type: str | None = None,
    kind: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    rows = await activity_service.list_activity(
        db, limit=limit, offset=offset, entity_type=entity_type, kind=kind
    )
    return [
        ActivityRow(
            id=r.id, occurred_at=r.occurred_at, kind=r.kind,
            entity_type=r.entity_type, entity_id=r.entity_id,
            summary=r.summary, details=r.details,
        )
        for r in rows
    ]


@router.get("/activity-log/count")
async def activity_log_count(db: AsyncSession = Depends(get_db)):
    return {"count": await activity_service.count_activity(db)}


# ---- Inventory report ------------------------------------------------- #


@router.get("/inventory-report", response_class=HTMLResponse)
async def inventory_report(
    include_disposed: bool = False,
    include_photos: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Print-friendly HTML report. Use browser Print → Save as PDF."""
    html = await report_service.render_report(
        db, include_disposed=include_disposed, include_photos=include_photos
    )
    return HTMLResponse(html)


# ---- eBay creds + refresh -------------------------------------------- #


@router.get("/ebay/creds", response_model=EbayCredsStatus)
async def get_ebay_creds(db: AsyncSession = Depends(get_db)):
    app_id, cert_id, marketplace = await ebay_service._get_creds(db)  # noqa: SLF001
    return EbayCredsStatus(
        configured=bool(app_id and cert_id),
        app_id_masked=settings_service.mask_key(app_id) if app_id else None,
        marketplace=marketplace,
        detected_env=_detect_ebay_env(app_id),
    )


@router.put("/ebay/creds", response_model=EbayCredsStatus)
async def set_ebay_creds(data: EbayCredsUpdate, db: AsyncSession = Depends(get_db)):
    # Defensive normalization: strip surrounding whitespace AND any quotes
    # the user might have copied along with the value (very common when
    # pasting from a code snippet or env-var docs).
    def _clean(v: str) -> str:
        return v.strip().strip("'\"`")
    await settings_service._set_setting(db, ebay_service.EBAY_APP_ID_KEY, _clean(data.app_id))  # noqa: SLF001
    await settings_service._set_setting(db, ebay_service.EBAY_CERT_ID_KEY, _clean(data.cert_id))  # noqa: SLF001
    await settings_service._set_setting(db, ebay_service.EBAY_MARKETPLACE_KEY, data.marketplace.strip() or "EBAY_US")  # noqa: SLF001
    app_id, _cert, marketplace = await ebay_service._get_creds(db)  # noqa: SLF001
    return EbayCredsStatus(
        configured=True,
        app_id_masked=settings_service.mask_key(app_id) if app_id else None,
        marketplace=marketplace,
        detected_env=_detect_ebay_env(app_id),
    )


@router.delete("/ebay/creds", status_code=204)
async def delete_ebay_creds(db: AsyncSession = Depends(get_db)):
    await settings_service._set_setting(db, ebay_service.EBAY_APP_ID_KEY, None)  # noqa: SLF001
    await settings_service._set_setting(db, ebay_service.EBAY_CERT_ID_KEY, None)  # noqa: SLF001


@router.post("/ebay/test")
async def test_ebay_creds(db: AsyncSession = Depends(get_db)):
    """End-to-end probe of OAuth + Browse search. Returns {ok, stage, detail}."""
    return await ebay_service.verify_creds(db)


@router.post("/ebay/refresh/{hat_id}")
async def refresh_ebay_for_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    """Refresh eBay comp prices for a single hat. Returns the updated price block."""
    hat = await hat_service.get_hat(db, hat_id)
    try:
        result = await ebay_service.find_comps(
            db, brand=hat.brand, model=hat.model_name, style=hat.style,
        )
    except ebay_service.EbayError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    for k, v in result.items():
        setattr(hat, k, v)
    await db.commit()
    return result


# Need this here to fix a forward-ref: hat_service uses Case; importing it
# in module scope keeps the relationship loadable without round-trips.
_ = Case
