"""Analysis-queue visibility and bulk re-analysis.

The queue was invisible: a hat showed "Analyzing…" and there was no way to see
how many were waiting, whether the worker was even alive, or which hat was
holding things up. `/health/ready` carried a depth number, but that endpoint is
a healthcheck, not a UI.

Bulk re-analysis lives here because it is the thing that fills the queue: it is
how a prompt or pricing change is applied to hats that were analysed under the
old one, and watching it drain is exactly what the queue view is for.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.database import get_db
from headroom.models.hat import Hat
from headroom.schemas.admin import AnalysisQueueStatus, PendingHat, ReanalyzeAllResult
from headroom.services import analysis_queue

router = APIRouter()


@router.get("/analysis/queue", response_model=AnalysisQueueStatus)
async def analysis_queue_status(db: AsyncSession = Depends(get_db)):
    """What the analysis worker is doing right now.

    `queued` is the in-memory depth; `pending` is what the DB says, which is the
    honest number — it survives a restart and includes anything the worker has
    picked up but not finished. They differ by design and both are useful: a
    non-empty `pending` with `worker_alive: false` means nothing is draining.
    """
    # Entities rather than columns: `display_id` is a derived property that
    # walks `hat.case`, so it can't be selected — and it's the label a person
    # actually recognises. Bounded to 50, which is a backlog list, not a report.
    hats = (
        (
            await db.execute(
                select(Hat)
                .options(selectinload(Hat.case))
                .where(Hat.analysis_status == analysis_queue.PENDING)
                .order_by(Hat.id)
                .limit(50)
            )
        )
        .scalars()
        .all()
    )

    return AnalysisQueueStatus(
        worker_alive=analysis_queue.worker_alive(),
        queued=analysis_queue.queue_depth(),
        pending_count=len(hats),
        pending=[
            PendingHat(
                id=h.id,
                display_id=h.display_id,
                label=" ".join(p for p in (h.brand, h.model_name) if p) or None,
                photo_path=h.photo_path,
                stage=h.analysis_stage,
            )
            for h in hats
        ],
    )


@router.post("/analysis/reanalyze-all", response_model=ReanalyzeAllResult)
async def reanalyze_all(
    db: AsyncSession = Depends(get_db),
    only_priced_by_claude: bool = Query(
        False,
        description=(
            "Limit to hats whose price came from Claude, leaving hand-entered"
            " prices alone."
        ),
    ),
):
    """Re-run analysis for every hat that has a photo.

    The reason this exists is retroactive correction: the pricing anchors added
    in 2.8.0 only affect hats analysed *after* them, so without this a
    collection keeps whatever estimates it was given under the old prompt.

    Cheap enough to be worth it — background removal is skipped for a stored
    cutout, so this is a Claude call per hat rather than the full pipeline —
    but it is still minutes of work, which is why it goes through the queue
    rather than blocking the request.

    Disposed hats are excluded: they're gone, and re-pricing them spends
    Claude calls on inventory you no longer own.
    """
    stmt = select(Hat.id).where(
        Hat.photo_path.is_not(None), Hat.disposed_at.is_(None)
    )
    if only_priced_by_claude:
        stmt = stmt.where(Hat.estimated_new_price_source == "Claude Vision")

    hat_ids = list((await db.execute(stmt.order_by(Hat.id))).scalars().all())
    if not hat_ids:
        return ReanalyzeAllResult(queued=0, worker_alive=analysis_queue.worker_alive())

    await db.execute(
        Hat.__table__.update()
        .where(Hat.id.in_(hat_ids))
        .values(
            analysis_status=analysis_queue.PENDING,
            analysis_error=None,
            analyzed_at=None,
        )
    )
    await db.commit()

    # If no worker is draining, the rows still read 'pending' and the boot sweep
    # picks them up on next start — the work is queued either way, which is what
    # the response reports.
    for hat_id in hat_ids:
        analysis_queue.enqueue(hat_id)

    return ReanalyzeAllResult(
        queued=len(hat_ids), worker_alive=analysis_queue.worker_alive()
    )
