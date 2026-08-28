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

import re

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.analysis_job import AnalysisJob
from headroom.models.hat import Hat
from headroom.services import hat_service
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


#: Substrings that mean "your Anthropic ACCOUNT is the problem, not your key".
#: Kept explicit because this is the failure that masquerades as a missing key,
#: and the one an owner will otherwise spend days re-pasting a valid key over.
_BILLING_MARKERS = (
    "credit balance is too low",
    "billing",
    "quota",
    "insufficient_quota",
    "payment",
)

#: Cap on how much of a failure string is used to group by. API errors carry a
#: request id and other per-call noise; without a cap every hat looks like its
#: own unique problem, which is the opposite of what grouping is for.
_REASON_KEY_CHARS = 160


def _reason_key(error: str) -> str:
    """The part of a failure string that identifies the FAILURE, not the call."""
    cleaned = re.sub(r"'request_id':\s*'[^']*'", "", error)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:_REASON_KEY_CHARS]


async def recent_failures(db: AsyncSession, limit: int = 10) -> list[dict]:
    """Distinct analysis failures across active hats, worst first.

    Exists because the only place a failure was legible was one hat's own page,
    and the banner there printed generic advice instead of the reason. An
    Anthropic billing refusal took down all 235 hats and read, everywhere, as
    "add an API key" — which was already set. A count and the actual text answer
    that in one glance.
    """
    rows = (
        await db.execute(
            select(Hat.id, Hat.analysis_error, Hat.analyzed_at)
            .where(
                Hat.disposed_at.is_(None),
                Hat.analysis_error.is_not(None),
                Hat.analysis_error != "",
            )
            .order_by(Hat.analyzed_at.desc())
        )
    ).all()

    # What a retry could actually queue, taken from the very function the retry
    # route calls rather than re-derived here. The two numbers differ for a real
    # reason: "Photo missing before analysis could run." is a failure worth
    # SEEING and impossible to retry, so filtering those rows out of this view
    # would hide the one message that explains why a hat is stuck. Deriving the
    # count instead of restating the rule means a button labeled "Retry 21"
    # queues 21 — by construction, not by two filters agreeing today.
    retryable = set(await hat_service.ids_for_reanalysis(db, failed_only=True))

    groups: dict[str, dict] = {}
    for hat_id, error, analyzed_at in rows:
        key = _reason_key(error or "")
        g = groups.setdefault(key, {
            "reason": key,
            "hat_count": 0,
            "retryable_count": 0,
            "sample_hat_ids": [],
            "last_seen": None,
            "is_billing": any(m in key.lower() for m in _BILLING_MARKERS),
        })
        g["hat_count"] += 1
        if hat_id in retryable:
            g["retryable_count"] += 1
        if len(g["sample_hat_ids"]) < 5:
            g["sample_hat_ids"].append(hat_id)
        if analyzed_at and (g["last_seen"] is None or analyzed_at > g["last_seen"]):
            g["last_seen"] = analyzed_at

    ordered = sorted(groups.values(), key=lambda g: -g["hat_count"])
    return ordered[:limit]


async def ids_for_failure_reason(db: AsyncSession, reason: str) -> list[int]:
    """Ids of the hats in ONE failure group — the inverse of `recent_failures`.

    Retrying a whole collection to fix 21 hats is the thing this avoids: on a
    234-hat shelf a transient `529 Overloaded` leaves a handful of casualties,
    and re-running everything to catch them costs a Claude call per hat that
    was already fine.

    Matching happens in Python rather than SQL, and that is forced by what a
    group IS: `_reason_key` is a CLEANED, truncated form of the raw failure
    string. A `WHERE analysis_error = :reason` would match almost nothing,
    since the stored text still carries the per-call request id the key strips
    — which is exactly why grouping needs a key in the first place.

    The incoming reason is re-keyed too. It arrives as a key already (the card
    sends back what this module produced), and `_reason_key` is idempotent, so
    this costs nothing and means a hand-made API call can pass raw error text
    and still hit the right group.
    """
    rows = (
        await db.execute(
            select(Hat.id, Hat.analysis_error).where(
                *hat_service.reanalyzable_filters(),
                *hat_service.failed_analysis_filters(),
            )
        )
    ).all()

    key = _reason_key(reason)
    return sorted(hat_id for hat_id, error in rows if _reason_key(error or "") == key)


async def _counts(db: AsyncSession, job_id: int) -> tuple[int, int, int]:
    """(finished, failed, still_pending) for a job, straight from the hats."""
    row = (
        await db.execute(
            select(
                func.count(Hat.id).filter(Hat.analysis_status != PENDING),
                func.count(Hat.id).filter(Hat.analysis_status == "error"),
                func.count(Hat.id).filter(Hat.analysis_status == PENDING),
            ).where(Hat.analysis_job_id == job_id)
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


async def progress_for(db: AsyncSession, job: AnalysisJob) -> JobProgress:
    """Derive counts, and close the job once nothing is left pending.

    Closing here rather than in the worker is what keeps the worker ignorant of
    jobs. The cost is that a finished job stays 'running' until someone looks —
    which is fine, because the only thing that reads it is the thing looking.
    """
    done, failed, pending = await _counts(db, job.id)
    # Gated on "nothing is left PENDING", which is what this docstring has
    # always said, rather than on `done >= job.total`.
    #
    # `total` is frozen at creation while the counts are over surviving rows,
    # so deleting one hat mid-run (the Duplicates page does exactly this) left
    # `done` one short forever: the job reported itself in flight permanently,
    # across restarts, and a second `reanalyze-all` re-tagged every hat and
    # stranded the first one identically. Asking about pending rows cannot
    # drift from reality, because the rows ARE the progress — which is the
    # claim in this module's own header.
    if job.status == RUNNING and pending == 0:
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


async def job_by_id(db: AsyncSession, job_id: int) -> AnalysisJob | None:
    """One run, by id. `None` when it has aged out or never existed."""
    return (
        await db.execute(select(AnalysisJob).where(AnalysisJob.id == job_id))
    ).scalar_one_or_none()


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
