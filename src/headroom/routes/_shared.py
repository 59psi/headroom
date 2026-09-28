"""What the two outside-facing surfaces — share links and guest view — have in common.

Both serve the same `SharedHat` projection and stream photos through a route
of their own rather than the session-gated `/uploads` mount. Each module
carried its own copy of the URL building (three times over), the photo route
and the 404 factory; this is the one copy, parameterized by where on the URL
space each surface lives.
"""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings
from headroom.models.hat import Hat
from headroom.schemas.share import SharedHat
from headroom.services import share_link_service
from headroom.utils import paths


def not_found(detail: str) -> HTTPException:
    """A fresh 404 per raise.

    A FACTORY, not a module-level instance. This was `_NOT_FOUND =
    HTTPException(...)` re-raised on every request, and CPython prepends each
    raise's frames onto the exception's existing `__traceback__` — so one
    shared object grew a traceback chain for the life of the process, pinning
    every request's locals (`Request`, `AsyncSession`, the response) with it.
    Measured: 0 → 30 retained frames after five anonymous requests. On an
    unauthenticated route, that is a slow leak anyone on the network can drive.
    """
    return HTTPException(status_code=404, detail=detail)


def shared_hat(hat: Hat, photo_base: str) -> SharedHat:
    """`hat` as an outsider sees it, its photos served under `photo_base`.

    `photo_base` is the surface's photo route without the id —
    `/api/public/guest/photo` or `/api/public/share/<token>/photo` — so the
    thumbnail is the same route with `?variant=thumb`, on both.
    """
    return share_link_service.to_shared_hat(
        hat,
        f"{photo_base}/{hat.id}" if hat.photo_path else None,
        f"{photo_base}/{hat.id}?variant=thumb" if hat.thumb_path else None,
    )


def shared_hats(hats: Iterable[Hat], photo_base: str) -> list[SharedHat]:
    return [shared_hat(h, photo_base) for h in hats]


async def photo_response(
    db: AsyncSession, hat_id: int, variant: str | None, *, missing: str
) -> FileResponse:
    """Stream one shared hat's photo, or 404 with `missing` as the detail.

    `shared_hat` re-checks `disposed_at` rather than trusting the caller — the
    id arrives straight from the URL, and a disposed hat is not on show.
    `photo_path` is checked here rather than inside it: that helper answers
    "may an outsider see this hat", a different question from "does it have a
    photo to serve". And `photo_path` is app-generated, but it reaches the
    filesystem here on an unauthenticated route, so it goes through the same
    containment check as every other client-influenced path.
    """
    hat = await share_link_service.shared_hat(db, hat_id)
    if hat is None or not hat.photo_path:
        raise not_found(missing)
    photo = paths.safe_file(settings.upload_dir, share_link_service.photo_variant(hat, variant))
    if photo is None:
        raise not_found(missing)
    return FileResponse(photo)
