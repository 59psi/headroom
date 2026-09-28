"""Read-only collection share links.

Two routers, because the two halves have opposite auth. Management (`router`,
/api/share-links) requires a session — the gate middleware, and `require_user`
applied where `routes/__init__.py` includes it. Public consumption
(`public_router`, /api/public/share/{token}) is exempt from auth by design:
the token IS the credential (256-bit, random, revocable, optionally
expiring). Photos are streamed through a token-gated endpoint rather than the
session-protected /uploads mount. One router for both meant the route-level
guard could only go on per decorator — and three management routes had none.

This module is transport only: token validity and what a token may see live in
`share_link_service`, the payload shapes in `schemas/share.py`, and what this
surface shares with guest view in `routes/_shared.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.routes import _shared
from headroom.routes._api import DomainErrorRoute
from headroom.schemas.share import (
    SharedCollection,
    ShareLinkCreate,
    ShareLinkCreated,
    ShareLinkRead,
)
from headroom.services import share_link_service

router = APIRouter(tags=["share-links"], route_class=DomainErrorRoute)
public_router = APIRouter(tags=["share-links"], route_class=DomainErrorRoute)

#: Every failure to resolve a token answers identically — see `ShareLinkInvalid`.
_LINK_NOT_FOUND = "Share link not found"
_PHOTO_NOT_FOUND = "Photo not found"


def _url_path(token: str) -> str:
    """Where a token is used. The route layer owns the URL space."""
    return f"/share/{token}"


def _photo_base(token: str) -> str:
    return f"/api/public/share/{token}/photo"


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
        raise _shared.not_found(_LINK_NOT_FOUND)


# ------------------------------- public -------------------------------- #


@public_router.get("/api/public/share/{token}", response_model=SharedCollection)
async def public_collection(token: str, db: AsyncSession = Depends(get_db)):
    try:
        link = await share_link_service.resolve_token(db, token)
    except share_link_service.ShareLinkInvalid:
        raise _shared.not_found(_LINK_NOT_FOUND) from None

    hats = await share_link_service.shared_hats(db)
    return SharedCollection(
        label=link.label,
        hat_count=len(hats),
        hats=_shared.shared_hats(hats, _photo_base(token)),
    )


@public_router.get("/api/public/share/{token}/photo/{hat_id}", response_class=FileResponse)
async def public_photo(
    token: str, hat_id: int, variant: str | None = None, db: AsyncSession = Depends(get_db)
):
    try:
        await share_link_service.resolve_token(db, token)
    except share_link_service.ShareLinkInvalid:
        raise _shared.not_found(_PHOTO_NOT_FOUND) from None
    return await _shared.photo_response(db, hat_id, variant, missing=_PHOTO_NOT_FOUND)
