"""Read-only collection share links.

Management lives under /api/share-links (session required via the gate
middleware). Public consumption lives under /api/public/share/{token} —
exempt from auth by design: the token IS the credential (256-bit, random,
revocable, optionally expiring). Photos are streamed through a token-gated
endpoint rather than the session-protected /uploads mount.

This module is transport only: token validity and what a token may see live in
`share_link_service`, the payload shapes in `schemas/share.py`, and the
path-containment check in `utils/paths.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings
from headroom.database import get_db
from headroom.schemas.share import (
    SharedCollection,
    ShareLinkCreate,
    ShareLinkCreated,
    ShareLinkRead,
)
from headroom.services import share_link_service
from headroom.services.share_link_service import ShareLinkInvalid
from headroom.utils.paths import safe_file

router = APIRouter(tags=["share-links"])

def _not_found() -> HTTPException:
    """Every failure to resolve a token answers identically — see `ShareLinkInvalid`.

    A factory rather than a shared instance, for the reason `routes/guest.py`
    documents: a module-level exception re-raised per request accumulates
    traceback frames forever, and `/api/public/share/<junk>` is anonymous.
    """
    return HTTPException(status_code=404, detail="Share link not found")


def _url_path(token: str) -> str:
    """Where a token is used. The route layer owns the URL space."""
    return f"/share/{token}"


# ----------------------------- management ----------------------------- #


@router.get("/api/share-links", response_model=list[ShareLinkRead])
async def list_share_links(db: AsyncSession = Depends(get_db)):
    links = await share_link_service.list_links(db)
    # Built field-by-field rather than validated off the ORM object: `url_path`
    # is not a column, and the URL space belongs to this layer.
    return [
        ShareLinkRead(
            id=link.id,
            token=link.token,
            label=link.label,
            created_at=link.created_at,
            expires_at=link.expires_at,
            revoked_at=link.revoked_at,
            url_path=_url_path(link.token),
        )
        for link in links
    ]


@router.post("/api/share-links", status_code=201, response_model=ShareLinkCreated)
async def create_share_link(data: ShareLinkCreate, db: AsyncSession = Depends(get_db)):
    link = await share_link_service.create_link(
        db, label=data.label, expires_days=data.expires_days
    )
    return ShareLinkCreated(
        id=link.id, token=link.token, url_path=_url_path(link.token)
    )


@router.delete("/api/share-links/{link_id}", status_code=204)
async def revoke_share_link(link_id: int, db: AsyncSession = Depends(get_db)):
    if await share_link_service.revoke_link(db, link_id) is None:
        raise _not_found()


# ------------------------------- public -------------------------------- #


@router.get("/api/public/share/{token}", response_model=SharedCollection)
async def public_collection(token: str, db: AsyncSession = Depends(get_db)):
    try:
        link = await share_link_service.resolve_token(db, token)
    except ShareLinkInvalid:
        raise _not_found() from None

    hats = await share_link_service.shared_hats(db)
    return SharedCollection(
        label=link.label,
        hat_count=len(hats),
        hats=[
            share_link_service.to_shared_hat(
                h,
                f"/api/public/share/{token}/photo/{h.id}" if h.photo_path else None,
            )
            for h in hats
        ],
    )


@router.get("/api/public/share/{token}/photo/{hat_id}", response_class=FileResponse)
async def public_photo(token: str, hat_id: int, db: AsyncSession = Depends(get_db)):
    try:
        await share_link_service.resolve_token(db, token)
    except ShareLinkInvalid:
        raise HTTPException(status_code=404, detail="Photo not found") from None

    hat = await share_link_service.shared_hat(db, hat_id)
    # `photo_path` checked here rather than inside `shared_hat`: that helper
    # answers "may an outsider see this hat", which is a different question
    # from "does it have a photo to serve".
    if hat is None or not hat.photo_path:
        raise HTTPException(status_code=404, detail="Photo not found")
    # `photo_path` is app-generated, but it reaches the filesystem here on an
    # unauthenticated route, so it goes through the same containment check as
    # every other client-influenced path rather than a local copy of one.
    photo = safe_file(settings.upload_dir, hat.photo_path)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(photo)
