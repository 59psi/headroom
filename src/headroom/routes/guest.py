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
from headroom.schemas.share import SharedCollection, SharedHat
from headroom.services import guest_view_service, share_link_service
from headroom.utils.paths import safe_file

router = APIRouter(prefix="/api/public/guest", tags=["guest"])

def _not_found() -> HTTPException:
    """One answer for every route in this module when guest view is off, so a
    guest cannot tell a disabled feature from an unrouted path.

    A FACTORY, not a module-level instance. This was `_NOT_FOUND =
    HTTPException(...)` re-raised on every request, and CPython prepends each
    raise's frames onto the exception's existing `__traceback__` — so one
    shared object grew a traceback chain for the life of the process, pinning
    every request's locals (`Request`, `AsyncSession`, the response) with it.
    Measured: 0 → 30 retained frames after five anonymous requests. On an
    unauthenticated route, that is a slow leak anyone on the network can drive.
    """
    return HTTPException(status_code=404, detail="Not found")


async def _require_enabled(db: AsyncSession) -> None:
    if not await guest_view_service.is_enabled(db):
        raise _not_found()


@router.get("/collection", response_model=SharedCollection)
async def guest_collection(
    q: str | None = Query(None, max_length=200),
    color_scope: str = Query("major", max_length=10),
    db: AsyncSession = Depends(get_db),
):
    """Browse, or search with `?q=`.

    Returns the same `SharedHat` projection a share link does — no prices, no
    purchase history, no disposition, no wear counts, no analysis state, no
    owner notes.
    """
    await _require_enabled(db)

    hats = await guest_view_service.guest_hats(db, q, color_scope)
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


@router.get("/photo/{hat_id}", response_class=FileResponse)
async def guest_photo(hat_id: int, db: AsyncSession = Depends(get_db)):
    await _require_enabled(db)

    # `shared_hat` re-checks `disposed_at` rather than trusting the caller —
    # the id arrives straight from the URL, and a disposed hat is not on show.
    hat = await share_link_service.shared_hat(db, hat_id)
    if hat is None or not hat.photo_path:
        raise _not_found()

    # `photo_path` is app-generated, but this is an unauthenticated route
    # reaching the filesystem, so it goes through the same containment check as
    # every other client-influenced path rather than a local copy of one.
    photo = safe_file(settings.upload_dir, hat.photo_path)
    if photo is None:
        raise _not_found()
    return FileResponse(photo)


@router.get("/hat/{hat_id}", response_model=SharedHat)
async def guest_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    """One hat, as an outside viewer sees it.

    Same projection as the listing — so this adds no field the grid did not
    already carry. It exists for the deep link: "where does this one live" is
    the question a guest actually has, and answering it should survive being
    sent to somebody.

    Disposed hats 404 here as they do everywhere else on this surface; the id
    arrives straight from the URL, so `shared_hat` re-checks rather than
    trusting that the caller came from the listing.
    """
    await _require_enabled(db)

    hat = await share_link_service.shared_hat(db, hat_id)
    if hat is None:
        raise _not_found()

    return share_link_service.to_shared_hat(
        hat, f"/api/public/guest/photo/{hat.id}" if hat.photo_path else None
    )
