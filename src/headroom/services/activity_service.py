"""Append-only audit log.

`log_activity()` is fire-and-forget — failures are swallowed so a logging
glitch can never crash a write path. Retention pruning runs from the
existing scheduler in app.lifespan.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import env_int
from headroom.models.activity_log import ActivityLog
from headroom.services.task_health import TaskHealth

logger = logging.getLogger(__name__)


def retention_days() -> int:
    """The retention window, live from the environment.

    Public because the admin endpoint reports it beside the health record: "0
    rows removed" reads as either "nothing was old enough" or "nothing ran",
    and the window is what tells them apart.
    """
    return max(1, env_int("HEADROOM_ACTIVITY_LOG_RETENTION_DAYS", 90))


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


async def log_and_commit(db: AsyncSession, **kwargs) -> None:
    """Append an audit row and commit it, without ever failing the caller.

    For the common shape where the domain write has ALREADY been committed and
    the audit row is a second, separate transaction. `log_activity` never
    raises, but the commit that follows it does — and this codebase treats
    SQLite's "database is locked" as an expected condition under worker
    contention, which is exactly when it would fire. Propagating it turned an
    already-durable change into a 500, so the client would report failure for a
    write that succeeded and a person would retry it, duplicating the work.

    An audit row is worth less than a correct response. Losing one is logged
    loudly; failing the request over it is not an option.
    """
    await log_activity(db, **kwargs)
    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — the domain write already landed
        logger.warning("activity_log commit failed (change itself is saved): %s", exc)
        await db.rollback()


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


#: Outcome of the last retention sweep — see `task_health.TaskHealth`.
#:
#: Here rather than in `app.py`, which owns the loop: a module-level record in
#: the app factory is not importable by a route without dragging the whole
#: application in, and retention is this module's concept. The loop prunes
#: sessions too, so the count is both tables combined — the question an
#: operator has is "is retention still running", not which table it touched.
retention_health = TaskHealth(name="retention prune")


async def prune_activity(db: AsyncSession) -> int:
    """Delete activity_log rows older than the retention window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days())
    result = await db.execute(delete(ActivityLog).where(ActivityLog.occurred_at < cutoff))
    await db.commit()
    deleted = result.rowcount or 0
    if deleted:
        logger.info("Pruned %d activity_log rows older than %d days", deleted, retention_days())
    return deleted
