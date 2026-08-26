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

import asyncio
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
from headroom.utils.upload import copy_upload_truncating

logger = logging.getLogger(__name__)

#: Ceiling on ONE shared batch. Mirrors `routes/import_jobs._MAX_TOTAL_UPLOAD_BYTES`
#: — same operation, same machine, same SD card.
_MAX_TOTAL_SHARE_BYTES = 750 * 1024 * 1024

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
        total = 0
        for idx, f in enumerate(incoming[:import_service.MAX_FILES_PER_JOB]):
            if not validate_image_content_type(f.content_type):
                logger.info("Share-target rejected non-image: %s", f.content_type)
                continue
            name = Path(f.filename or "shared.jpg").name
            dest = staging / f"{idx:04d}-{name[:120]}"
            # The SHARED helper, off the event loop — identical to what
            # `routes/import_jobs` does, because this is the same operation.
            # This carried its own copy of the chunk loop until 2.57.2, which
            # is how `utils/upload.py` came to claim "one definition, used by
            # all" while four existed. It also ran on the event loop, so a
            # 20 MB share blocked every other request for the duration.
            with dest.open("wb") as out:
                written = await asyncio.to_thread(
                    copy_upload_truncating, f, out, import_service.MAX_BYTES_PER_FILE
                )
            total += written
            # A per-file cap is not a cap. The share sheet will hand over a
            # whole camera roll selection, and 100 x 20 MB is 2 GB written to a
            # Pi's SD card in one unattended request — the disk exhaustion
            # `utils/disk.py` exists to notice, caused by the app itself.
            # `routes/import_jobs` has enforced this since it was written;
            # sharing from the phone was the path without it.
            if total > _MAX_TOTAL_SHARE_BYTES:
                logger.warning(
                    "Share-target batch over %d MB — keeping the first %d file(s)",
                    _MAX_TOTAL_SHARE_BYTES // 1024 // 1024, len(files),
                )
                dest.unlink(missing_ok=True)
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
