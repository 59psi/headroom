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

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.services import import_service
from headroom.utils.photo import validate_image_content_type

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/share")
async def share_target(
    photos: list[UploadFile] | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Receive shared photos and queue a bulk-import job."""
    incoming = photos or []
    valid: list[tuple[str, bytes]] = []
    for f in incoming:
        if not validate_image_content_type(f.content_type):
            logger.info("Share-target rejected non-image: %s", f.content_type)
            continue
        valid.append((f.filename or "shared.jpg", await f.read()))

    if not valid:
        # No usable files — bounce them to the regular import page.
        return RedirectResponse("/hats/import", status_code=303)

    job = await import_service.create_job(
        db, files=valid,
        defaults={"condition": "new", "size": "classic", "style": "a_game"},
    )
    return RedirectResponse(f"/hats/import?job={job.id}", status_code=303)
