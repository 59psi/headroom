"""Unauthenticated, read-only browsing of the collection.

Mounted under `/api/public/`, which `AuthGateMiddleware` leaves open. Every
route here 404s unless the owner has explicitly switched guest view on — see
`services/guest_view_service` for why 404 rather than 403.

There are no non-GET routes in this module, and there is no path by which one
should be added: a guest reads.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.routes import _shared
from headroom.routes._api import DomainErrorRoute
from headroom.schemas.search import MAX_QUERY_LENGTH, ColorScope
from headroom.schemas.share import SharedCollection, SharedHat
from headroom.services import guest_view_service, share_link_service

router = APIRouter(prefix="/api/public/guest", tags=["guest"], route_class=DomainErrorRoute)

#: Where this surface serves photos; `_shared` appends the id.
_PHOTO_BASE = "/api/public/guest/photo"

#: One answer for every route in this module when guest view is off, so a
#: guest cannot tell a disabled feature from an unrouted path.
_NOT_FOUND = "Not found"


async def _require_enabled(db: AsyncSession) -> None:
    if not await guest_view_service.is_enabled(db):
        raise _shared.not_found(_NOT_FOUND)


@router.get("/collection", response_model=SharedCollection)
async def guest_collection(
    q: str | None = Query(None, max_length=MAX_QUERY_LENGTH),
    color_scope: ColorScope = Query(ColorScope.major),
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
        hats=_shared.shared_hats(hats, _PHOTO_BASE),
    )


@router.get("/photo/{hat_id}", response_class=FileResponse)
async def guest_photo(hat_id: int, variant: str | None = None, db: AsyncSession = Depends(get_db)):
    await _require_enabled(db)
    return await _shared.photo_response(db, hat_id, variant, missing=_NOT_FOUND)


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
        raise _shared.not_found(_NOT_FOUND)
    return _shared.shared_hat(hat, _PHOTO_BASE)
