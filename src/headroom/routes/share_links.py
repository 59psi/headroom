"""Read-only collection share links.

Management lives under /api/share-links (session required via the gate
middleware). Public consumption lives under /api/public/share/{token} —
exempt from auth by design: the token IS the credential (256-bit, random,
revocable, optionally expiring). Photos are streamed through a token-gated
endpoint rather than the session-protected /uploads mount.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.config import settings
from headroom.database import get_db
from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.models.user import ShareLink
from headroom.services.activity_service import log_activity

router = APIRouter(tags=["share-links"])


# ----------------------------- management ----------------------------- #


class ShareLinkCreate(BaseModel):
    label: str = Field("Shared collection", max_length=80)
    expires_days: int | None = Field(None, ge=1, le=365)


@router.get("/api/share-links")
async def list_share_links(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ShareLink).order_by(ShareLink.id.desc()))
    return [
        {
            "id": link.id,
            "token": link.token,
            "label": link.label,
            "url_path": f"/share/{link.token}",
            "created_at": link.created_at,
            "expires_at": link.expires_at,
            "revoked_at": link.revoked_at,
        }
        for link in result.scalars().all()
    ]


@router.post("/api/share-links", status_code=201)
async def create_share_link(data: ShareLinkCreate, db: AsyncSession = Depends(get_db)):
    link = ShareLink(
        token=secrets.token_urlsafe(32),
        label=data.label,
        expires_at=(
            datetime.now(timezone.utc) + timedelta(days=data.expires_days)
            if data.expires_days
            else None
        ),
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    await log_activity(
        db, kind="share.created", entity_type="share_link", entity_id=link.id,
        summary=f"Share link '{link.label}' created (exposes the full active collection)",
    )
    await db.commit()
    return {"id": link.id, "token": link.token, "url_path": f"/share/{link.token}"}


@router.delete("/api/share-links/{link_id}", status_code=204)
async def revoke_share_link(link_id: int, db: AsyncSession = Depends(get_db)):
    link = await db.get(ShareLink, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Share link not found")
    link.revoked_at = datetime.now(timezone.utc)
    await log_activity(
        db, kind="share.revoked", entity_type="share_link", entity_id=link.id,
        summary=f"Share link '{link.label}' revoked",
    )
    await db.commit()


# ------------------------------- public -------------------------------- #


async def _valid_link(db: AsyncSession, token: str) -> ShareLink:
    result = await db.execute(select(ShareLink).where(ShareLink.token == token))
    link = result.scalar_one_or_none()
    if link is None or link.revoked_at is not None:
        raise HTTPException(status_code=404, detail="Share link not found")
    if link.expires_at is not None:
        expires = link.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail="Share link expired")
    return link


@router.get("/api/public/share/{token}")
async def public_collection(token: str, db: AsyncSession = Depends(get_db)):
    link = await _valid_link(db, token)
    result = await db.execute(
        select(Hat)
        .options(selectinload(Hat.case).selectinload(Case.room), selectinload(Hat.colors))
        .where(Hat.disposed_at.is_(None))
        .order_by(Hat.id)
    )
    hats = list(result.scalars().all())
    return {
        "label": link.label,
        "hat_count": len(hats),
        "hats": [
            {
                "id": h.id,
                "display_id": h.display_id,
                "brand": h.brand,
                "model_name": h.model_name,
                "style": h.style,
                "photo_url": (
                    f"/api/public/share/{token}/photo/{h.id}" if h.photo_path else None
                ),
                "colors": [
                    {"name": c.general_color or c.color_name, "hex": c.hex_value}
                    for c in (h.colors or [])
                ],
                "case": h.case.display_id if h.case else None,
                "room": h.case.room.name if h.case and h.case.room else None,
            }
            for h in hats
        ],
    }


@router.get("/api/public/share/{token}/photo/{hat_id}")
async def public_photo(token: str, hat_id: int, db: AsyncSession = Depends(get_db)):
    await _valid_link(db, token)
    hat = await db.get(Hat, hat_id)
    if hat is None or not hat.photo_path or hat.disposed_at is not None:
        raise HTTPException(status_code=404, detail="Photo not found")
    photo = (settings.upload_dir / hat.photo_path).resolve()
    # Photos live under the upload dir by construction; verify anyway.
    if not photo.is_relative_to(settings.upload_dir.resolve()) or not photo.is_file():
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(photo)
