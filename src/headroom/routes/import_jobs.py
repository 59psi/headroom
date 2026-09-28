"""Bulk hat-photo import endpoints."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.routes import _uploads
from headroom.routes._api import DomainErrorRoute
from headroom.schemas.hat import HAT_DEFAULTS, HatCondition, HatSize, HatStyle
from headroom.schemas.import_job import ImportJobCreated, ImportJobRead
from headroom.services import hat_service, import_service

router = APIRouter(
    prefix="/api/hats/import", tags=["bulk-import"], route_class=DomainErrorRoute
)


@router.post("", status_code=202, response_model=ImportJobCreated)
async def create_import_job(
    photos: list[UploadFile],
    case_id: Annotated[int | None, Form()] = None,
    # Typed with the enums `HatCreate` validates against. As bare `str` a typo
    # was accepted with a 202, the whole batch was spooled, and then every
    # item failed in the worker with "3 validation errors for HatCreate".
    condition: Annotated[HatCondition, Form()] = HatCondition(HAT_DEFAULTS["condition"]),
    size: Annotated[HatSize, Form()] = HatSize(HAT_DEFAULTS["size"]),
    style: Annotated[HatStyle, Form()] = HatStyle(HAT_DEFAULTS["style"]),
    db: AsyncSession = Depends(get_db),
):
    """Multipart upload of N photo files. Returns the job ID immediately."""
    if not photos:
        raise HTTPException(status_code=400, detail="No photos provided")
    # Reject an over-count batch BEFORE reading any bytes (`create_job` checks
    # too, but by then every file has been spooled to disk).
    if len(photos) > import_service.MAX_FILES_PER_JOB:
        raise HTTPException(
            status_code=413,
            detail=f"Max {import_service.MAX_FILES_PER_JOB} files per job",
        )
    # The case too, for the same reason: a missing or full case is known now,
    # and finding it out in the worker costs the whole upload first.
    if case_id is not None:
        await hat_service.ensure_case_accepts(db, case_id, style)

    # Each file goes to disk as it arrives, and only its path is kept. This
    # used to accumulate every blob in a list and check the total AFTER the
    # loop, so a full batch was resident at once — up to the 750MB cap, which
    # is well over the container's memory limit, on the box whose OOM kill this
    # release exists to prevent. Peak is now one file (20MB), not the batch.
    staging = Path(tempfile.mkdtemp(prefix="upload-", dir=import_service.spool_dir()))
    try:
        files = await _uploads.spool_batch(photos, staging, strict=True, default_name="photo.jpg")
        defaults = {
            "case_id": case_id,
            "condition": condition.value,
            "size": size.value,
            "style": style.value,
        }
        job = await import_service.create_job(db, files=files, defaults=defaults)
        return ImportJobCreated(id=job.id, total=job.total, status=job.status)
    finally:
        # `create_job` MOVES what it keeps into the job's own staging dir, so
        # this spool dir is always disposable — including on the 413/400 paths,
        # where leaving it would strand a batch of photos until reboot.
        shutil.rmtree(staging, ignore_errors=True)


@router.get("/{job_id}", response_model=ImportJobRead)
async def get_import_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await import_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    return job


@router.get("", response_model=list[ImportJobRead])
async def list_import_jobs(
    limit: int = Query(20, ge=1, le=200), db: AsyncSession = Depends(get_db)
):
    return await import_service.list_recent_jobs(db, limit=limit)


@router.delete("/{job_id}", response_model=ImportJobRead)
async def cancel_import_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await import_service.cancel_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    return job
