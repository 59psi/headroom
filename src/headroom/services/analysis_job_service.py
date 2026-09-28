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

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings as config_settings
from headroom.models.analysis_job import AnalysisJob
from headroom.models.hat import Hat
from headroom.services import hat_analysis_pipeline, hat_service, settings_service
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


#: Why a failed hat cannot be retried RIGHT NOW. A retry of one of these can
#: only fail the same way again, so it is not offered — and the card says
#: which, because the two need opposite things from the owner.
#:
#: No photo: the row names no photo, or names a file that is gone from disk.
#: Nothing fixes that but a new photo.
NO_PHOTO = "no_photo"
#: No Claude key: the hat failed for want of one and there still is none.
#: Retryable again the moment a key is added — so this is decided against the
#: key as configured NOW, not against the failure text alone.
NO_API_KEY = "no_api_key"


def _missing_photos(paths: dict[int, str | None]) -> set[int]:
    """Ids whose photo is absent — no path, or a path to nothing. Filesystem
    stats, so the caller runs this off the event loop."""
    root = config_settings.upload_dir
    return {hat_id for hat_id, path in paths.items() if not path or not (root / path).is_file()}


async def _unretryable(
    db: AsyncSession, rows: list[tuple[int, str | None, str | None]]
) -> dict[int, str]:
    """`{hat_id: NO_PHOTO | NO_API_KEY}` for the failing rows `(id, error, photo_path)`
    that a retry cannot help. Every other row is worth retrying.

    The retry used to be offered for anything with a `photo_path`, which is a
    question about the ROW: a hat whose file had been moved off disk read
    "Retry 1 hat", and the retry 404'd on the same missing file; a keyless
    install was offered a retry of every hat, each of which could only fall
    back again.
    """
    missing = await asyncio.to_thread(_missing_photos, {h: p for h, _e, p in rows})
    key, _source = await settings_service.get_anthropic_key(db)
    out: dict[int, str] = {}
    for hat_id, error, _path in rows:
        if hat_id in missing:
            out[hat_id] = NO_PHOTO
        elif not key and (error or "").startswith(hat_analysis_pipeline.NO_ANTHROPIC_KEY):
            out[hat_id] = NO_API_KEY
    return out


async def expected_failure_prefix(db: AsyncSession) -> str | None:
    """The failure text that is not an alarm on this install RIGHT NOW.

    With no Claude key configured, `NO_ANTHROPIC_KEY` on a hat is the expected
    result of Basic ID, not a failure to flag: the nav badge and the error
    list leave it out (`hat_service._alarming_failure_filters`), while the
    failures card keeps it as one `NO_API_KEY` group — the "Add a key" nudge.
    Judged against the key as configured now, like `_unretryable`: add a key
    and the same hats count again, because a retry can now help them.
    """
    key, _source = await settings_service.get_anthropic_key(db)
    return None if key else hat_analysis_pipeline.NO_ANTHROPIC_KEY


async def _failing_rows(db: AsyncSession) -> list[tuple[int, str | None, str | None]]:
    """`(id, error, photo_path)` for every reanalyzable hat carrying a failure —
    the set a retry draws from, before `_unretryable` narrows it."""
    return [
        (hat_id, error, path)
        for hat_id, error, path in (
            await db.execute(
                select(Hat.id, Hat.analysis_error, Hat.photo_path).where(
                    *hat_service.reanalyzable_filters(),
                    *hat_service.failed_analysis_filters(),
                )
            )
        ).all()
    ]


async def retryable_failure_ids(db: AsyncSession, reason: str | None = None) -> list[int]:
    """Ids a retry should queue: failing hats a retry can actually help.

    The ONE definition, used by the failures card for its counts and by the
    retry itself for what it queues — so "Retry 21" queues 21 by
    construction. `reason` narrows to one failure group (see
    `ids_for_failure_reason`); None is every retryable failure.
    """
    rows = await _failing_rows(db)
    if reason is not None:
        key = _reason_key(reason)
        rows = [r for r in rows if _reason_key(r[1] or "") == key]
    blocked = await _unretryable(db, rows)
    return sorted(hat_id for hat_id, _e, _p in rows if hat_id not in blocked)


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
            select(Hat.id, Hat.analysis_error, Hat.analyzed_at, Hat.photo_path)
            .where(Hat.disposed_at.is_(None), *hat_service.failed_analysis_filters())
            .order_by(Hat.analyzed_at.desc())
        )
    ).all()

    # What a retry could actually queue, from the very function the retry
    # calls rather than re-derived here. The two numbers differ for real
    # reasons — a photo that is gone, a key that is still missing — and those
    # failures are worth SEEING even though a retry cannot help: filtering them
    # out of this view would hide the one message that explains why a hat is
    # stuck. Deriving the count instead of restating the rule means a button
    # labeled "Retry 21" queues 21 — by construction, not by two filters
    # agreeing today.
    retryable = set(await retryable_failure_ids(db))
    # Why the rest cannot be retried, for the card to say. Computed over every
    # row shown, including ones with no photo at all (which `_failing_rows`
    # never considers, since there is nothing to re-analyze).
    blocked = await _unretryable(db, [(h, e, p) for h, e, _at, p in rows])

    groups: dict[str, dict] = {}
    why_not: dict[str, set[str]] = {}
    for hat_id, error, analyzed_at, _path in rows:
        key = _reason_key(error or "")
        g = groups.setdefault(key, {
            "reason": key,
            "hat_count": 0,
            "retryable_count": 0,
            "unretryable_reason": None,
            "sample_hat_ids": [],
            "last_seen": None,
            "is_billing": any(m in key.lower() for m in _BILLING_MARKERS),
        })
        g["hat_count"] += 1
        if hat_id in retryable:
            g["retryable_count"] += 1
        elif hat_id in blocked:
            why_not.setdefault(key, set()).add(blocked[hat_id])
        if len(g["sample_hat_ids"]) < 5:
            g["sample_hat_ids"].append(hat_id)
        if analyzed_at and (g["last_seen"] is None or analyzed_at > g["last_seen"]):
            g["last_seen"] = analyzed_at

    for key, reasons in why_not.items():
        # A missing key outranks a missing photo when one group has both: it
        # is the one the owner can fix from Settings in a minute.
        groups[key]["unretryable_reason"] = NO_API_KEY if NO_API_KEY in reasons else NO_PHOTO

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

    Only the hats a retry can help: the group's count on the card and this
    list come from the same `retryable_failure_ids`.
    """
    return await retryable_failure_ids(db, reason)


async def _counts(db: AsyncSession, job_id: int) -> tuple[int, int, int]:
    """(finished, failed, still_pending) for a job, straight from the hats."""
    row = (
        await db.execute(
            select(
                func.count(Hat.id).filter(Hat.analysis_status != PENDING),
                # "Failed" is a non-empty `analysis_error`, never a status: a
                # Claude outage degrades hats to `fallback`/`skipped` WITH a
                # reason, and `== "error"` counted none of them — so during a
                # total outage this read 0 while `failed_count` on the same
                # payload (from `count_for_analysis_job`) read every hat. One
                # predicate, owned by `hat_service.failed_analysis_filters`.
                func.count(Hat.id).filter(*hat_service.failed_analysis_filters()),
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
