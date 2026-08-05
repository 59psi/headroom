"""Append-only audit log browsing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.admin import ActivityRow
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


@router.get("/activity-log/count")
async def activity_log_count(db: AsyncSession = Depends(get_db)):
    return {"count": await activity_service.count_activity(db)}
