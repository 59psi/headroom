"""Analysis-queue visibility and bulk re-analysis.

The queue was invisible: a hat showed "Analyzing…" and there was no way to see
how many were waiting, whether the worker was even alive, or which hat was
holding things up. `/health/ready` carried a depth number, but that endpoint is
a healthcheck, not a UI.

Bulk re-analysis lives here because it is the thing that fills the queue: it is
how a prompt or pricing change is applied to hats that were analyzed under the
old one, and watching it drain is exactly what the queue view is for.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.admin import (
    AnalysisFailureGroup,
    AnalysisJobRead,
    AnalysisQueueStatus,
    PendingHat,
    ReanalyzeAllResult,
)
from headroom.services import analysis_job_service, hat_service, analysis_queue

router = APIRouter()


async def _queue_run(db: AsyncSession, hat_ids: list[int]) -> ReanalyzeAllResult:
    """Open a job over these hats, queue them, and report what happened.

    Shared by the whole-collection run and the retry-failed run because the
    tail is identical and the interesting part is only ever which ids go in.
    Two copies of this would be two places for the `create_job`-then-commit
    ordering to drift, and the half that lost it would enqueue ids whose rows
    were never marked pending.
    """
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
    in 2.8.0 only affect hats analyzed *after* them, so without this a
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
    return await _queue_run(db, await hat_service.ids_for_reanalysis(db))


@router.post("/analysis/retry-failed", response_model=ReanalyzeAllResult)
async def retry_failed_analysis(
    reason: str | None = Query(
        None,
        description="Retry only the hats in this failure group. Omit for all failures.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Re-run analysis for the hats that FAILED it, not the whole collection.

    A transient upstream failure — `529 Overloaded` is the one that actually
    happens — takes out a scattering of hats mid-run. Before this the only
    repair was "Re-analyze every hat", which on a 234-hat collection spends a
    Claude call on 213 hats that were already correct in order to fix 21.

    `reason` narrows further, to one group from the failures card. Those groups
    are not interchangeable: an overload wants retrying immediately, while a
    response the parser choked on will choke again and is a bug report, not a
    retry. Making the whole card one button would force them to be treated the
    same.

    Nothing is queued twice: `create_job` moves the hats to `pending` and
    clears their failure text, so a second press finds a smaller set — or an
    empty one, reported honestly as `queued: 0`.
    """
    hat_ids = (
        await analysis_job_service.ids_for_failure_reason(db, reason)
        if reason
        else await hat_service.ids_for_reanalysis(db, failed_only=True)
    )
    return await _queue_run(db, hat_ids)


@router.get("/analysis/failures", response_model=list[AnalysisFailureGroup])
async def analysis_failures(db: AsyncSession = Depends(get_db)):
    """Why hats are failing analysis, grouped, worst first.

    The only place a failure used to be legible was a single hat's own page,
    where the banner printed generic advice rather than the reason. One
    Anthropic billing refusal took down all 235 hats and read everywhere as
    "add an API key" — which was already set, valid, and had been working.
    """
    return [
        AnalysisFailureGroup(**group)
        for group in await analysis_job_service.recent_failures(db)
    ]
