"""Bulk re-analysis runs, tracked as jobs.

Progress is derived, never accumulated. The analysis worker drains hat ids and
knows nothing about jobs — it should not have to, and making it update a
counter per hat would mean two writes per item with a crash between them
leaving a progress bar permanently out of step with the hats it describes.

So a job stores only what cannot be recomputed (`total`, when it started), and
everything else is a COUNT over `hats.analysis_job_id`. That is always right by
construction, including after a restart mid-run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.analysis_job import AnalysisJob
from headroom.models.hat import Hat
from headroom.services.analysis_queue import PENDING

RUNNING = "running"
DONE = "done"

# How many past runs the Settings card shows. A short history — enough to
# answer "did the last one finish, and did anything fail?" — not an audit log.
RECENT_LIMIT = 5


@dataclass(frozen=True)
class JobProgress:
    """A job plus the counts derived from the hats tagged with it."""

    job: AnalysisJob
    done: int
    failed: int

    @property
    def remaining(self) -> int:
        return max(0, self.job.total - self.done)


async def create_job(db: AsyncSession, hat_ids: list[int]) -> AnalysisJob:
    """Tag the hats and open a job over them. Caller commits."""
    job = AnalysisJob(total=len(hat_ids), status=RUNNING)
    db.add(job)
    await db.flush()  # need the id before tagging

    await db.execute(
        update(Hat)
        .where(Hat.id.in_(hat_ids))
        .values(
            analysis_job_id=job.id,
            analysis_status=PENDING,
            analysis_error=None,
            analyzed_at=None,
        )
    )
    return job


async def _counts(db: AsyncSession, job_id: int) -> tuple[int, int]:
    """(finished, failed) for a job, straight from the hats."""
    row = (
        await db.execute(
            select(
                func.count(Hat.id).filter(Hat.analysis_status != PENDING),
                func.count(Hat.id).filter(Hat.analysis_status == "error"),
            ).where(Hat.analysis_job_id == job_id)
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0)


async def progress_for(db: AsyncSession, job: AnalysisJob) -> JobProgress:
    """Derive counts, and close the job once nothing is left pending.

    Closing here rather than in the worker is what keeps the worker ignorant of
    jobs. The cost is that a finished job stays 'running' until someone looks —
    which is fine, because the only thing that reads it is the thing looking.
    """
    done, failed = await _counts(db, job.id)
    if job.status == RUNNING and done >= job.total:
        job.status = DONE
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
    return JobProgress(job=job, done=done, failed=failed)


async def current_job(db: AsyncSession) -> JobProgress | None:
    """The run still in flight, if there is one."""
    job = (
        await db.execute(
            select(AnalysisJob)
            .where(AnalysisJob.status == RUNNING)
            .order_by(AnalysisJob.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        return None
    progress = await progress_for(db, job)
    # It may have just been closed by the call above; then it isn't current.
    return None if progress.job.status != RUNNING else progress


async def recent_jobs(db: AsyncSession, limit: int = RECENT_LIMIT) -> list[JobProgress]:
    jobs = (
        (
            await db.execute(
                select(AnalysisJob).order_by(AnalysisJob.id.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [await progress_for(db, job) for job in jobs]
