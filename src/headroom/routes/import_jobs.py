"""Bulk hat-photo import endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.services import import_service
from headroom.utils.photo import validate_image_content_type

router = APIRouter(prefix="/api/hats/import", tags=["bulk-import"])


def _job_to_dict(job) -> dict:
    return {
        "id": job.id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "total": job.total,
        "done": job.done,
        "errors": job.errors,
        "skipped": job.skipped,
        "status": job.status,
        "items": [
            {
                "id": i.id,
                "filename": i.filename,
                "status": i.status,
                "hat_id": i.hat_id,
                "error": i.error,
                "bytes": i.bytes,
            }
            for i in (job.items or [])
        ],
    }


@router.post("", status_code=202)
async def create_import_job(
    photos: list[UploadFile],
    case_id: Annotated[int | None, Form()] = None,
    condition: Annotated[str, Form()] = "new",
    size: Annotated[str, Form()] = "classic",
    style: Annotated[str, Form()] = "a_game",
    db: AsyncSession = Depends(get_db),
):
    """Multipart upload of N photo files. Returns the job ID immediately."""
    if not photos:
        raise HTTPException(status_code=400, detail="No photos provided")

    files: list[tuple[str, bytes]] = []
    for p in photos:
        if not validate_image_content_type(p.content_type):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid content type for {p.filename}: {p.content_type}",
            )
        blob = await p.read()
        files.append((p.filename or "photo.jpg", blob))

    defaults = {
        "case_id": case_id,
        "condition": condition,
        "size": size,
        "style": style,
    }
    job = await import_service.create_job(db, files=files, defaults=defaults)
    return {"id": job.id, "total": job.total, "status": job.status}


@router.get("/{job_id}")
async def get_import_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await import_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    return _job_to_dict(job)


@router.get("")
async def list_import_jobs(limit: int = 20, db: AsyncSession = Depends(get_db)):
    jobs = await import_service.list_recent_jobs(db, limit=limit)
    return [_job_to_dict(j) for j in jobs]


@router.delete("/{job_id}")
async def cancel_import_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await import_service.cancel_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    return _job_to_dict(job)
