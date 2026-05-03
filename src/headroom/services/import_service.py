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
from headroom.schemas.hat import HatCreate, HatStyle
from headroom.services import hat_service
from headroom.services.activity_service import log_activity
from headroom.services.hat_analysis_pipeline import finalize_hat_photo
from headroom.utils.photo import process_image_async

logger = logging.getLogger(__name__)

MAX_FILES_PER_JOB = 100
MAX_BYTES_PER_FILE = 20 * 1024 * 1024  # 20 MB

_queue: asyncio.Queue[int] | None = None  # holds item IDs
_worker_task: asyncio.Task | None = None


def staging_dir() -> Path:
    d = config_settings.upload_dir / ".import-staging"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def create_job(
    db: AsyncSession,
    *,
    files: list[tuple[str, bytes]],
    defaults: dict | None = None,
) -> ImportJob:
    """Stage files to disk, create a job + items, enqueue them. Returns the job."""
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

    for idx, (filename, blob) in enumerate(files):
        if len(blob) > MAX_BYTES_PER_FILE:
            db.add(ImportJobItem(
                job_id=job.id, filename=filename, status="error",
                error=f"File exceeds {MAX_BYTES_PER_FILE // 1024 // 1024} MB limit",
                bytes=len(blob),
            ))
            job.errors += 1
            continue
        # Stage the file before commit so the worker has something to read
        safe_name = f"{idx:04d}-{Path(filename).name[:120]}"
        staged = job_dir / safe_name
        staged.write_bytes(blob)
        db.add(ImportJobItem(
            job_id=job.id, filename=filename, status="queued",
            bytes=len(blob), staged_path=str(staged),
        ))
    await db.commit()
    await log_activity(
        db, kind="import.created", entity_type="system", entity_id=job.id,
        summary=f"Bulk import job #{job.id} queued with {len(files)} file(s)",
    )
    await db.commit()

    # Enqueue each queued item
    if _queue is not None:
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
    async with async_session() as db:
        result = await db.execute(
            select(ImportJobItem).where(ImportJobItem.id == item_id)
        )
        item = result.scalar_one_or_none()
        if item is None or item.status != "queued":
            return  # already cancelled or processed
        result = await db.execute(
            select(ImportJob).where(ImportJob.id == item.job_id)
        )
        job = result.scalar_one()
        if job.status == "cancelled":
            return

        # Mark running
        item.status = "processing"
        if job.status == "queued":
            job.status = "running"
        await db.commit()

    # The actual heavy work needs its own session lifecycle so the upload
    # pipeline's commit/expire semantics work cleanly.
    try:
        async with async_session() as db:
            result = await db.execute(
                select(ImportJobItem).where(ImportJobItem.id == item_id)
            )
            item = result.scalar_one()
            staged = Path(item.staged_path) if item.staged_path else None
            if staged is None or not staged.exists():
                raise FileNotFoundError("staged file missing")

            # Resolve defaults from the job
            result = await db.execute(
                select(ImportJob).where(ImportJob.id == item.job_id)
            )
            job = result.scalar_one()
            defaults = json.loads(job.defaults_json or "{}")
            create_data = HatCreate(
                case_id=defaults.get("case_id"),
                condition=defaults.get("condition", "new"),
                size=defaults.get("size", "classic"),
                style=defaults.get("style", "a_game"),
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
            result = await db.execute(
                select(ImportJobItem).where(ImportJobItem.id == item_id)
            )
            item = result.scalar_one()
            item.status = "done"
            item.hat_id = hat.id
            await db.commit()

            # Update job progress + cleanup staged file
            staged.unlink(missing_ok=True)
            await _bump_job_counter(item.job_id, "done")

    except Exception as exc:  # noqa: BLE001 — never crash the worker
        logger.warning("Import item %s failed: %s", item_id, exc)
        async with async_session() as db:
            result = await db.execute(
                select(ImportJobItem).where(ImportJobItem.id == item_id)
            )
            item = result.scalar_one_or_none()
            if item:
                item.status = "error"
                item.error = str(exc)[:1000]
                await db.commit()
                if item.staged_path:
                    Path(item.staged_path).unlink(missing_ok=True)
        await _bump_job_counter(item_id and item.job_id or 0, "errors")


async def _bump_job_counter(job_id: int, field: str) -> None:
    """Increment the matching counter on the job and check completion."""
    if not job_id:
        return
    async with async_session() as db:
        result = await db.execute(
            select(ImportJob).where(ImportJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            return
        if field == "done":
            job.done += 1
        elif field == "errors":
            job.errors += 1
        elif field == "skipped":
            job.skipped += 1
        # Job done if every item is in a terminal state
        if job.done + job.errors + job.skipped >= job.total:
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
            finally:
                _queue.task_done()
    except asyncio.CancelledError:
        logger.info("Import worker cancelled.")
        raise


async def start_worker() -> None:
    """Wire up the queue + worker. Called from app.lifespan."""
    global _queue, _worker_task
    _queue = asyncio.Queue()
    _worker_task = asyncio.create_task(_worker_loop())
    # Re-enqueue any items that were left in 'queued' state from a prior boot
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
