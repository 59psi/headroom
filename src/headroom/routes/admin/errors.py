"""Recent analysis failures — the nav badge and the Settings error list."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.admin import RecentError
from headroom.models.hat import Hat
from headroom.services import hat_service

router = APIRouter()


def _safe_display_id(hat: Hat) -> str | None:
    """display_id depends on hat.case being loaded; tolerate missing relationship."""
    try:
        return hat.display_id
    except Exception:  # noqa: BLE001
        return None


@router.get("/recent-errors", response_model=list[RecentError])
async def recent_errors(limit: int = 20, db: AsyncSession = Depends(get_db)):
    """Most recent hats with analysis_status='error', newest first."""
    rows = await hat_service.list_by_analysis_status(
        db, "error", limit=limit, newest_first=True
    )
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


@router.get("/recent-errors/count")
async def recent_errors_count(db: AsyncSession = Depends(get_db)):
    """Cheap count for nav-badge display."""
    return {"count": await hat_service.count_by_analysis_status(db, "error")}
