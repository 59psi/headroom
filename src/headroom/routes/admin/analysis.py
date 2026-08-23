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

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.admin import (
    AnalysisJobRead,
    AnalysisQueueStatus,
    PendingHat,
    ReanalyzeAllResult,
)
from headroom.services import analysis_job_service, hat_service, analysis_queue

router = APIRouter()


def _job_read(p) -> AnalysisJobRead:
    return AnalysisJobRead(
        id=p.job.id,
        total=p.job.total,
        done=p.done,
        failed=p.failed,
        status=p.job.status,
        started_at=p.job.started_at,
        finished_at=p.job.finished_at,
    )


@router.get("/analysis/queue", response_model=AnalysisQueueStatus)
async def analysis_queue_status(db: AsyncSession = Depends(get_db)):
    """What the analysis worker is doing right now.

    `queued` is the in-memory depth; `pending` is what the DB says, which is the
    honest number — it survives a restart and includes anything the worker has
    picked up but not finished. They differ by design and both are useful: a
    non-empty `pending` with `worker_alive: false` means nothing is draining.
    """
    # The LIST is bounded to 50 — this is a backlog preview, not a report.
    # The COUNT is not: `pending_count` used to be `len(hats)`, which silently
    # capped the number at 50 no matter how deep the queue really was. Same
    # mistake as reading a collection size off a limited autocomplete feed.
    hats = await hat_service.list_by_analysis_status(
        db, analysis_queue.PENDING, limit=50
    )
    pending_total = await hat_service.count_by_analysis_status(
        db, analysis_queue.PENDING
    )

    current = await analysis_job_service.current_job(db)
    recent = await analysis_job_service.recent_jobs(db)

    return AnalysisQueueStatus(
        worker_alive=analysis_queue.worker_alive(),
        queued=analysis_queue.queue_depth(),
        current_job=_job_read(current) if current else None,
        recent_jobs=[_job_read(p) for p in recent],
        pending_count=pending_total,
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
async def reanalyze_all(db: AsyncSession = Depends(get_db)):
    """Re-run analysis for every hat that has a photo.

    The reason this exists is retroactive correction: the pricing anchors added
    in 2.8.0 only affect hats analysed *after* them, so without this a
    collection keeps whatever estimates it was given under the old prompt.

    Cheap enough to be worth it — background removal is skipped for a stored
    cutout, so this is a Claude call per hat rather than the full pipeline —
    but it is still minutes of work, which is why it goes through the queue
    rather than blocking the request.

    Disposed hats are excluded: they're gone, and re-pricing them spends
    Claude calls on inventory you no longer own. That is the ONLY exclusion —
    see `hat_service.ids_for_reanalysis` for the filter that used to sit here
    and quietly cut a 234-hat collection down to 45.
    """
    hat_ids = await hat_service.ids_for_reanalysis(db)
    if not hat_ids:
        return ReanalyzeAllResult(queued=0, worker_alive=analysis_queue.worker_alive())

    job = await analysis_job_service.create_job(db, hat_ids)
    await db.commit()

    # If no worker is draining, the rows still read 'pending' and the boot sweep
    # picks them up on next start — the work is queued either way, which is what
    # the response reports.
    for hat_id in hat_ids:
        analysis_queue.enqueue(hat_id)

    progress = await analysis_job_service.progress_for(db, job)
    return ReanalyzeAllResult(
        queued=len(hat_ids),
        worker_alive=analysis_queue.worker_alive(),
        job=_job_read(progress),
    )
