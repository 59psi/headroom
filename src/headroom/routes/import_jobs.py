"""Bulk hat-photo import endpoints."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.hat import HAT_DEFAULTS
from headroom.schemas.import_job import ImportJobCreated, ImportJobRead
from headroom.services import import_service
from headroom.utils.photo import validate_image_content_type

router = APIRouter(prefix="/api/hats/import", tags=["bulk-import"])

# Ceiling on the total bytes accepted for one request. Files are spooled to
# disk as they arrive rather than buffered, so this now bounds disk and job
# size rather than RAM. Phone photos are a few MB, so this is
# generous for real use while blocking the pathological case (S9/R6 — docs/AUDIT-HISTORY.md).
_MAX_TOTAL_UPLOAD_BYTES = 750 * 1024 * 1024




@router.post("", status_code=202, response_model=ImportJobCreated)
async def create_import_job(
    photos: list[UploadFile],
    case_id: Annotated[int | None, Form()] = None,
    condition: Annotated[str, Form()] = HAT_DEFAULTS["condition"],
    size: Annotated[str, Form()] = HAT_DEFAULTS["size"],
    style: Annotated[str, Form()] = HAT_DEFAULTS["style"],
    db: AsyncSession = Depends(get_db),
):
    """Multipart upload of N photo files. Returns the job ID immediately."""
    if not photos:
        raise HTTPException(status_code=400, detail="No photos provided")
    # Reject an over-count batch BEFORE reading any bytes (create_job also
    # checks, but only after everything is in memory).
    if len(photos) > import_service.MAX_FILES_PER_JOB:
        raise HTTPException(
            status_code=413,
            detail=f"Max {import_service.MAX_FILES_PER_JOB} files per job",
        )

    # Each file goes to disk as it arrives, and only its path is kept. This
    # used to accumulate every blob in a list and check the total AFTER the
    # loop, so a full batch was resident at once — up to the 750MB cap, which
    # is well over the container's memory limit, on the box whose OOM kill this
    # release exists to prevent. Peak is now one file (20MB), not the batch.
    staging = Path(tempfile.mkdtemp(prefix="headroom-upload-"))
    files: list[tuple[str, Path]] = []
    total = 0
    try:
        for index, p in enumerate(photos):
            if not validate_image_content_type(p.content_type):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid content type for {p.filename}: {p.content_type}",
                )
            dest = staging / f"{index:04d}"
            with dest.open("wb") as fh:
                written = await asyncio.to_thread(
                    _spool, p, fh, import_service.MAX_BYTES_PER_FILE
                )
            total += written
            if total > _MAX_TOTAL_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Upload batch exceeds {_MAX_TOTAL_UPLOAD_BYTES // 1024 // 1024} MB "
                        "in total — split it into smaller batches."
                    ),
                )
            files.append((p.filename or "photo.jpg", dest))

        defaults = {
            "case_id": case_id,
            "condition": condition,
            "size": size,
            "style": style,
        }
        job = await import_service.create_job(db, files=files, defaults=defaults)
        return ImportJobCreated(id=job.id, total=job.total, status=job.status)
    finally:
        # `create_job` copies what it keeps into the job's own staging dir, so
        # this temp copy is always disposable — including on the 413/400 paths,
        # where leaving it would strand a batch of photos until reboot.
        shutil.rmtree(staging, ignore_errors=True)


def _spool(upload, dest, cap: int) -> int:
    """Copy an upload to `dest`, stopping just past `cap`. Returns bytes written.

    Lenient like `read_capped`: an oversize file is truncated rather than
    rejected, so `create_job` still records it as a skipped item and the rest of
    the batch proceeds.
    """
    written = 0
    while True:
        chunk = upload.file.read(1024 * 1024)
        if not chunk:
            break
        dest.write(chunk)
        written += len(chunk)
        if written > cap:
            break
    return written


@router.get("/{job_id}", response_model=ImportJobRead)
async def get_import_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await import_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    return job


@router.get("", response_model=list[ImportJobRead])
async def list_import_jobs(limit: int = 20, db: AsyncSession = Depends(get_db)):
    return await import_service.list_recent_jobs(db, limit=limit)


@router.delete("/{job_id}", response_model=ImportJobRead)
async def cancel_import_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await import_service.cancel_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    return job
