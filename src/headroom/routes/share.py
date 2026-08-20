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

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.hat import HAT_DEFAULTS
from headroom.services import import_service
from headroom.utils.photo import validate_image_content_type
from headroom.utils.upload import MAX_PHOTO_BYTES

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/share")
async def share_target(
    photos: list[UploadFile] | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Receive shared photos and queue a bulk-import job.

    Spools each file to a temp dir and hands `create_job` PATHS, exactly like
    the bulk-import route. This previously read whole files into memory and
    passed BYTES — which `create_job` cannot use at all: it calls
    `source.stat()` and `shutil.copy2(source, ...)`, so every share raised
    AttributeError on the first file. The route was both unbounded and broken,
    and nothing exercised it (Android-only, and no test covered the handler).
    """
    incoming = photos or []
    if not incoming:
        return RedirectResponse("/hats/import", status_code=303)

    staging = Path(tempfile.mkdtemp(prefix="share-"))
    try:
        files: list[tuple[str, Path]] = []
        for idx, f in enumerate(incoming[:import_service.MAX_FILES_PER_JOB]):
            if not validate_image_content_type(f.content_type):
                logger.info("Share-target rejected non-image: %s", f.content_type)
                continue
            name = Path(f.filename or "shared.jpg").name
            dest = staging / f"{idx:04d}-{name[:120]}"
            # Chunked and capped: one chunk in memory at a time, and an
            # oversize file stops just past the limit so `create_job` records
            # it as skipped rather than the whole share failing.
            with dest.open("wb") as out:
                written = 0
                while True:
                    chunk = await f.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    written += len(chunk)
                    if written > MAX_PHOTO_BYTES:
                        break
            files.append((name, dest))

        if not files:
            # No usable files — bounce them to the regular import page.
            return RedirectResponse("/hats/import", status_code=303)

        job = await import_service.create_job(
            db, files=files, defaults=dict(HAT_DEFAULTS),
        )
        return RedirectResponse(f"/hats/import?job={job.id}", status_code=303)
    finally:
        # `create_job` copies what it keeps into the job's own staging dir, so
        # these are always disposable — including on the error paths.
        shutil.rmtree(staging, ignore_errors=True)
