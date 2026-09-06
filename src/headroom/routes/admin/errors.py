"""Recent analysis failures — the nav badge and the Settings error list."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.admin import CountRead, RecentError
from headroom.services import hat_service

router = APIRouter()


@router.get("/recent-errors", response_model=list[RecentError])
async def recent_errors(limit: int = Query(20, ge=1, le=200), db: AsyncSession = Depends(get_db)):
    """Most recent hats carrying an analysis failure, newest first.

    Keyed on the failure TEXT (`hat_service.failed_analysis_filters`), not on
    `analysis_status == "error"`. The status predicate misses `fallback` and
    `skipped`, which both carry a reason — and `fallback` is where every hat
    lands when Claude is unreachable, so during a total outage this list and
    the badge below it were empty while the failures card listed the whole
    collection. The correct predicate had been sitting in `hat_service` the
    whole time with a docstring explaining why this one was wrong.
    """
    rows = await hat_service.list_failed_analyses(
        db, limit=limit, newest_first=True
    )
    return [
        RecentError(
            hat_id=h.id,
            display_id=h.display_id,
            analysis_error=h.analysis_error,
            analyzed_at=cast(datetime | None, h.analyzed_at),
            photo_path=h.photo_path,
        )
        for h in rows
    ]


@router.get("/recent-errors/count", response_model=CountRead)
async def recent_errors_count(db: AsyncSession = Depends(get_db)):
    """Cheap count for nav-badge display. Same predicate as the list above.

    A badge that counts a different set from the list it links to is worse
    than no badge — and that was the state: both read `analysis_status`, so
    both went quiet together in the one situation worth surfacing.
    """
    return {"count": await hat_service.count_failed_analyses(db)}
