"""Append-only audit log browsing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.admin import ActivityRow, CountRead, RetentionStatus
from headroom.services import activity_service

router = APIRouter()


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


@router.get("/activity-log/count", response_model=CountRead)
async def activity_log_count(db: AsyncSession = Depends(get_db)):
    return {"count": await activity_service.count_activity(db)}


@router.get("/activity-log/retention", response_model=RetentionStatus)
async def retention_status():
    """Is the daily prune still running, and what did it last remove?

    The row count next door cannot answer that: a table that is not growing
    and a prune that died three weeks ago look the same from a COUNT for as
    long as nothing is being written. This is the only thing bounding
    `activity_log` and `auth_sessions`, so a silent death ends in a full SD
    card — the same operational class as a failed backup, which has had a
    health endpoint for far longer.

    `retention_days` alongside the health record because "0 removed" has two
    readings — nothing was old enough, or nothing ran — and the window is what
    separates them.
    """
    return {
        "retention_days": activity_service.retention_days(),
        "health": activity_service.retention_health.snapshot(),
    }
