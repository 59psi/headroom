"""Bulk hat-photo import.

Single asyncio worker pulls items off a queue and runs them through the
existing photo + Claude pipeline one at a time. One worker is the right
concurrency level — rembg + Claude already serialize, so parallelism here
gains nothing and just complicates state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings as config_settings
from headroom.database import async_session
from headroom.models.hat import Hat
from headroom.models.import_job import ImportJob, ImportJobItem
from headroom.schemas.hat import HAT_DEFAULTS, HatCreate, HatStyle
from headroom.services import hat_service
from headroom.services.activity_service import log_activity
from headroom.services.hat_analysis_pipeline import finalize_hat_photo
from headroom.utils.photo import process_image_async

logger = logging.getLogger(__name__)

MAX_FILES_PER_JOB = 100
MAX_BYTES_PER_FILE = 20 * 1024 * 1024  # 20 MB

# Terminal item status -> the ImportJob counter column it feeds. The two names
# genuinely differ ("error" item, "errors" counter), which is exactly the slip a
# bare string parameter invites — so the increment path AND the boot-time
# recount both derive from this one mapping instead of restating it.
_JOB_COUNTER: dict[str, str] = {
    "done": "done",
    "error": "errors",
    "skipped": "skipped",
}

_queue: asyncio.Queue[int] | None = None  # holds item IDs
_worker_task: asyncio.Task | None = None


def staging_dir() -> Path:
    d = config_settings.upload_dir / ".import-staging"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def create_job(
    db: AsyncSession,
    *,
    files: list[tuple[str, Path]],
    defaults: dict | None = None,
) -> ImportJob:
    """Stage already-spooled files into the job dir, create it, enqueue. Returns the job.

    `files` is (original filename, path to a temp copy). Paths rather than
    bytes so a batch is never resident in memory — the caller spools each
    upload to disk as it arrives and deletes its temp dir afterwards.
    """
    if not files:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > MAX_FILES_PER_JOB:
        from fastapi import HTTPException
        raise HTTPException(status_code=413, detail=f"Max {MAX_FILES_PER_JOB} files per job")

    job = ImportJob(
        total=len(files),
        status="queued",
        defaults_json=json.dumps(defaults or {}),
    )
    db.add(job)
    await db.flush()  # need job.id for staging path

    job_dir = staging_dir() / f"job-{job.id}"
    job_dir.mkdir(parents=True, exist_ok=True)

    for idx, (filename, source) in enumerate(files):
        size = source.stat().st_size
        if size > MAX_BYTES_PER_FILE:
            db.add(ImportJobItem(
                job_id=job.id, filename=filename, status="error",
                error=f"File exceeds {MAX_BYTES_PER_FILE // 1024 // 1024} MB limit",
                bytes=size,
            ))
            job.errors += 1
            continue
        # Stage the file before commit so the worker has something to read.
        # `copy2`, not `read_bytes`+`write_bytes`: the caller has already spooled
        # this to disk precisely so a batch never sits in memory, and reading it
        # back to write it out again would undo that one file at a time.
        safe_name = f"{idx:04d}-{Path(filename).name[:120]}"
        staged = job_dir / safe_name
        shutil.copy2(source, staged)
        db.add(ImportJobItem(
            job_id=job.id, filename=filename, status="queued",
            bytes=size, staged_path=str(staged),
        ))
    # A job whose every file was rejected (all oversize) has no queued items to
    # drive it to completion — close it now so the SPA doesn't poll it forever.
    if job.errors >= job.total:
        job.status = "done"
        job.finished_at = datetime.now(timezone.utc)
    await db.commit()
    await log_activity(
        db, kind="import.created", entity_type="system", entity_id=job.id,
        summary=f"Bulk import job #{job.id} queued with {len(files)} file(s)",
    )
    await db.commit()

    # Enqueue each queued item
    if _queue is None:
        # No worker running (disabled by env, or start_worker never ran). The
        # items are safe — they stay 'queued' on disk and `start_worker`'s boot
        # sweep re-enqueues them — but until then the job sits at 0% with no
        # explanation, which reads as a hang. Bulk import cannot fall back to
        # running inline the way `analysis_queue` does; a batch takes minutes
        # and would hold the request open. So the honest fix is to say so.
        logger.warning(
            "Import job #%s queued with no worker running — items will not be "
            "processed until restart (HEADROOM_IMPORT_WORKER_ENABLED?).",
            job.id,
        )
    else:
        result = await db.execute(
            select(ImportJobItem).where(
                ImportJobItem.job_id == job.id,
                ImportJobItem.status == "queued",
            )
        )
        for item in result.scalars().all():
            _queue.put_nowait(item.id)

    return job


async def get_job(db: AsyncSession, job_id: int) -> ImportJob | None:
    result = await db.execute(
        select(ImportJob).where(ImportJob.id == job_id)
    )
    return result.scalar_one_or_none()


async def list_recent_jobs(db: AsyncSession, limit: int = 20) -> list[ImportJob]:
    result = await db.execute(
        select(ImportJob).order_by(ImportJob.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def cancel_job(db: AsyncSession, job_id: int) -> ImportJob | None:
    job = await get_job(db, job_id)
    if not job:
        return None
    if job.status in ("done", "cancelled"):
        return job
    job.status = "cancelled"
    # Mark queued items as cancelled — in-flight items finish naturally
    result = await db.execute(
        select(ImportJobItem).where(
            ImportJobItem.job_id == job_id,
            ImportJobItem.status == "queued",
        )
    )
    for item in result.scalars().all():
        item.status = "cancelled"
        if item.staged_path:
            Path(item.staged_path).unlink(missing_ok=True)
    await db.commit()
    await log_activity(
        db, kind="import.cancelled", entity_type="system", entity_id=job_id,
        summary=f"Bulk import job #{job_id} cancelled",
    )
    await db.commit()
    return job


# ---- Worker ---------------------------------------------------------- #


async def _process_item(item_id: int) -> None:
    # Claim the item in its own short transaction, capturing job_id up front
    # so the error handler always has it even if a later load returns None.
    async with async_session() as db:
        result = await db.execute(
            select(ImportJobItem).where(ImportJobItem.id == item_id)
        )
        item = result.scalar_one_or_none()
        if item is None or item.status != "queued":
            return  # already cancelled or processed
        job = await db.get(ImportJob, item.job_id)
        if job is not None and job.status == "cancelled":
            return
        job_id = item.job_id

    # Everything below runs under one try so that ANY failure — including a
    # transient "database is locked" on the mark-running commit — marks the
    # item errored and bumps the counter rather than escaping to the worker
    # loop. The loop has its own catch-all too (belt and suspenders).
    try:
        # Mark running
        async with async_session() as db:
            item = (await db.execute(
                select(ImportJobItem).where(ImportJobItem.id == item_id)
            )).scalar_one()
            item.status = "processing"
            job = await db.get(ImportJob, item.job_id)
            if job is not None and job.status == "queued":
                job.status = "running"
            await db.commit()

        # The heavy work needs its own session lifecycle so the upload
        # pipeline's commit/expire semantics work cleanly.
        async with async_session() as db:
            item = (await db.execute(
                select(ImportJobItem).where(ImportJobItem.id == item_id)
            )).scalar_one()
            staged = Path(item.staged_path) if item.staged_path else None
            if staged is None or not staged.exists():
                raise FileNotFoundError("staged file missing")

            # Resolve defaults from the job
            job = (await db.execute(
                select(ImportJob).where(ImportJob.id == item.job_id)
            )).scalar_one()
            defaults = json.loads(job.defaults_json or "{}")
            create_data = HatCreate(
                case_id=defaults.get("case_id"),
                condition=defaults.get("condition", HAT_DEFAULTS["condition"]),
                size=defaults.get("size", HAT_DEFAULTS["size"]),
                style=defaults.get("style", HAT_DEFAULTS["style"]),
            )

            # Create the hat row first
            hat = await hat_service.create_hat(db, create_data)

            # Process the photo (resize → bg-remove → Claude analysis)
            from headroom.utils.photo import generate_filename
            upload_dir = config_settings.upload_dir / "hats"
            upload_dir.mkdir(parents=True, exist_ok=True)
            filename = generate_filename(item.filename or "import.jpg")
            output_path = upload_dir / filename
            final_path = await process_image_async(staged, output_path)
            await finalize_hat_photo(db, hat, final_path)
            await db.commit()

            # Update the job item
            item = (await db.execute(
                select(ImportJobItem).where(ImportJobItem.id == item_id)
            )).scalar_one()
            item.status = "done"
            item.hat_id = hat.id
            await db.commit()

            # Update job progress + cleanup staged file
            staged.unlink(missing_ok=True)
        await _bump_job_counter(job_id, "done")

    except Exception as exc:  # noqa: BLE001 — never crash the worker
        logger.warning("Import item %s failed: %s", item_id, exc)
        try:
            async with async_session() as db:
                item = (await db.execute(
                    select(ImportJobItem).where(ImportJobItem.id == item_id)
                )).scalar_one_or_none()
                if item:
                    item.status = "error"
                    item.error = str(exc)[:1000]
                    await db.commit()
                    if item.staged_path:
                        Path(item.staged_path).unlink(missing_ok=True)
        except Exception as inner:  # noqa: BLE001 — bookkeeping must not raise
            logger.warning("Import item %s error-bookkeeping failed: %s", item_id, inner)
        await _bump_job_counter(job_id, "error")


async def _bump_job_counter(job_id: int, item_status: str) -> None:
    """Increment the counter matching a terminal item status, then check completion.

    Takes the status that was just written to the item, not the counter name, so
    the caller never has to know about the `error`/`errors` skew.
    """
    counter = _JOB_COUNTER.get(item_status)
    if not job_id or counter is None:
        return
    async with async_session() as db:
        result = await db.execute(
            select(ImportJob).where(ImportJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            return
        setattr(job, counter, getattr(job, counter) + 1)
        # Job done if every item is in a terminal state — but never resurrect a
        # cancelled job whose in-flight items are still finishing.
        if (
            job.status != "cancelled"
            and sum(getattr(job, c) for c in _JOB_COUNTER.values()) >= job.total
        ):
            job.status = "done"
            job.finished_at = datetime.now(timezone.utc)
        await db.commit()
        if job.status == "done":
            # Clean up the per-job staging directory
            jdir = staging_dir() / f"job-{job.id}"
            if jdir.exists():
                try:
                    shutil.rmtree(jdir)
                except OSError:
                    pass


async def _worker_loop() -> None:
    """Background task: drain the import queue forever."""
    assert _queue is not None
    logger.info("Import worker started.")
    try:
        while True:
            item_id = await _queue.get()
            try:
                await _process_item(item_id)
            except Exception as exc:  # noqa: BLE001 — one bad item must NOT
                # kill the worker; _process_item handles its own bookkeeping,
                # this is the last line of defence against an unforeseen escape.
                logger.exception("Import worker: unhandled error on item %s: %s", item_id, exc)
            finally:
                _queue.task_done()
    except asyncio.CancelledError:
        logger.info("Import worker cancelled.")
        raise


def worker_alive() -> bool:
    """True if the background import worker task exists and is still running.

    Surfaced by /health/ready so a silently-dead worker is visible to operators.
    """
    return _worker_task is not None and not _worker_task.done()


async def _recover_on_boot() -> None:
    """Heal jobs left mid-flight by a crash/OOM/restart before draining.

    A power loss on a Pi is a normal event, not an edge case: items caught in
    'processing' would otherwise never retry, and a job whose items are all
    terminal (e.g. every file oversize) would poll 'queued' forever in the SPA.
    """
    async with async_session() as db:
        # 1. Items stuck 'processing' when the process died.
        stuck = (await db.execute(
            select(ImportJobItem).where(ImportJobItem.status == "processing")
        )).scalars().all()
        for item in stuck:
            job = await db.get(ImportJob, item.job_id)
            # A cancelled job's in-flight item becomes cancelled; otherwise retry.
            item.status = "cancelled" if (job and job.status == "cancelled") else "queued"
        if stuck:
            await db.commit()

        # 2. Recompute counters and close any non-terminal job whose items are
        #    all terminal (covers all-oversize jobs and crash-during-finish).
        jobs = (await db.execute(
            select(ImportJob).where(ImportJob.status.in_(["queued", "running"]))
        )).scalars().all()
        for job in jobs:
            items = (await db.execute(
                select(ImportJobItem).where(ImportJobItem.job_id == job.id)
            )).scalars().all()
            for status, counter in _JOB_COUNTER.items():
                setattr(job, counter, sum(1 for i in items if i.status == status))
            if not any(i.status in ("queued", "processing") for i in items):
                job.status = "done"
                job.finished_at = datetime.now(timezone.utc)
        if jobs:
            await db.commit()


async def start_worker() -> None:
    """Wire up the queue + worker. Called from app.lifespan."""
    global _queue, _worker_task
    _queue = asyncio.Queue()
    _worker_task = asyncio.create_task(_worker_loop())
    # Heal crash-stranded state, then enqueue everything left 'queued'
    # (including items just reset from 'processing' by the boot sweep).
    await _recover_on_boot()
    async with async_session() as db:
        result = await db.execute(
            select(ImportJobItem).where(ImportJobItem.status == "queued")
        )
        for item in result.scalars().all():
            _queue.put_nowait(item.id)


async def stop_worker() -> None:
    global _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
