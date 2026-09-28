"""Web Share Target endpoint.

Wired to the manifest.json `share_target.action`. Android Chrome posts the
shared files here as multipart/form-data when the user shares photos to the
PWA. We hand the files to the existing bulk-import service and 303-redirect
the browser into `/hats/import?job=N` so the SPA can render the progress UI.

iOS Safari does not implement Web Share Target as of 2026 — iPhone users
follow the iOS-Shortcut recipe in Settings instead, which posts directly
to /api/hats/import.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.routes import _uploads
from headroom.routes._api import DomainErrorRoute
from headroom.schemas.hat import HAT_DEFAULTS
from headroom.services import import_service

router = APIRouter(route_class=DomainErrorRoute)


@router.post("/share", response_class=RedirectResponse)
async def share_target(
    photos: list[UploadFile] | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Receive shared photos and queue a bulk-import job.

    Spools each file to a temp dir and hands `create_job` PATHS, exactly like
    the bulk-import route — through the same `spool_batch`, in its lenient
    mode: the share sheet opens this as a page, so there is no error screen to
    show a 400 on. Non-images are skipped and a batch over the total cap keeps
    its leading files.
    """
    incoming = photos or []
    if not incoming:
        return RedirectResponse("/hats/import", status_code=303)

    staging = Path(tempfile.mkdtemp(prefix="share-", dir=import_service.spool_dir()))
    try:
        files = await _uploads.spool_batch(
            incoming[:import_service.MAX_FILES_PER_JOB],
            staging,
            strict=False,
            default_name="shared.jpg",
        )
        if not files:
            # No usable files — bounce them to the regular import page.
            return RedirectResponse("/hats/import", status_code=303)

        job = await import_service.create_job(
            db, files=files, defaults=dict(HAT_DEFAULTS),
        )
        return RedirectResponse(f"/hats/import?job={job.id}", status_code=303)
    finally:
        # `create_job` MOVES what it keeps into the job's own staging dir, so
        # these are always disposable — including on the error paths.
        shutil.rmtree(staging, ignore_errors=True)
