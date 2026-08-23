"""Unauthenticated, read-only browsing of the collection.

Mounted under `/api/public/`, which `AuthGateMiddleware` leaves open. Every
route here 404s unless the owner has explicitly switched guest view on — see
`services/guest_view_service` for why 404 rather than 403.

There are no non-GET routes in this module, and there is no path by which one
should be added: a guest reads.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings
from headroom.database import get_db
from headroom.schemas.share import SharedCollection
from headroom.services import guest_view_service, share_link_service
from headroom.utils.paths import safe_file

router = APIRouter(prefix="/api/public/guest", tags=["guest"])

#: Reused rather than raised inline so every route in this module is
#: indistinguishable from an unrouted path when guest view is off.
_NOT_FOUND = HTTPException(status_code=404, detail="Not found")


async def _require_enabled(db: AsyncSession) -> None:
    if not await guest_view_service.is_enabled(db):
        raise _NOT_FOUND


@router.get("/collection", response_model=SharedCollection)
async def guest_collection(
    q: str | None = Query(None, max_length=200),
    db: AsyncSession = Depends(get_db),
):
    """Browse, or search with `?q=`.

    Returns the same `SharedHat` projection a share link does — no prices, no
    purchase history, no disposition, no wear counts, no analysis state, no
    owner notes.
    """
    await _require_enabled(db)

    hats = await guest_view_service.guest_hats(db, q)
    return SharedCollection(
        label="The collection",
        hat_count=len(hats),
        hats=[
            share_link_service.to_shared_hat(
                h, f"/api/public/guest/photo/{h.id}" if h.photo_path else None
            )
            for h in hats
        ],
    )


@router.get("/photo/{hat_id}")
async def guest_photo(hat_id: int, db: AsyncSession = Depends(get_db)):
    await _require_enabled(db)

    # `shared_hat` re-checks `disposed_at` rather than trusting the caller —
    # the id arrives straight from the URL, and a disposed hat is not on show.
    hat = await share_link_service.shared_hat(db, hat_id)
    if hat is None or not hat.photo_path:
        raise _NOT_FOUND

    # `photo_path` is app-generated, but this is an unauthenticated route
    # reaching the filesystem, so it goes through the same containment check as
    # every other client-influenced path rather than a local copy of one.
    photo = safe_file(settings.upload_dir, hat.photo_path)
    if photo is None:
        raise _NOT_FOUND
    return FileResponse(photo)
