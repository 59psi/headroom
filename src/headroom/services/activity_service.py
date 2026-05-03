"""Append-only audit log.

`log_activity()` is fire-and-forget — failures are swallowed so a logging
glitch can never crash a write path. Retention pruning runs from the
existing scheduler in app.lifespan.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.activity_log import ActivityLog

logger = logging.getLogger(__name__)


def _retention_days() -> int:
    try:
        return max(1, int(os.environ.get("HEADROOM_ACTIVITY_LOG_RETENTION_DAYS", "90")))
    except ValueError:
        return 90


async def log_activity(
    db: AsyncSession,
    *,
    kind: str,
    entity_type: str,
    entity_id: int | None = None,
    summary: str,
    details: dict | None = None,
) -> None:
    """Write a row to activity_log. Never raises."""
    try:
        row = ActivityLog(
            kind=kind,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary[:200],
            details=json.dumps(details) if details else None,
        )
        db.add(row)
        # Caller's transaction will commit. If the caller never commits,
        # the row is rolled back along with their work — desired.
    except Exception as exc:  # noqa: BLE001 — never crash a write
        logger.warning("activity_log write failed: %s", exc)


async def list_activity(
    db: AsyncSession,
    limit: int = 100,
    offset: int = 0,
    entity_type: str | None = None,
    kind: str | None = None,
) -> list[ActivityLog]:
    stmt = select(ActivityLog).order_by(ActivityLog.occurred_at.desc(), ActivityLog.id.desc())
    if entity_type:
        stmt = stmt.where(ActivityLog.entity_type == entity_type)
    if kind:
        stmt = stmt.where(ActivityLog.kind == kind)
    stmt = stmt.offset(max(0, offset)).limit(max(1, min(limit, 500)))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_activity(db: AsyncSession) -> int:
    result = await db.execute(select(func.count(ActivityLog.id)))
    return int(result.scalar() or 0)


async def prune_activity(db: AsyncSession) -> int:
    """Delete activity_log rows older than the retention window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=_retention_days())
    result = await db.execute(delete(ActivityLog).where(ActivityLog.occurred_at < cutoff))
    await db.commit()
    deleted = result.rowcount or 0
    if deleted:
        logger.info("Pruned %d activity_log rows older than %d days", deleted, _retention_days())
    return deleted
