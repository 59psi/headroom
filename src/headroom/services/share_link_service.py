"""Share links: creation, revocation, and what a token is allowed to see.

The route module used to own all of this — persistence, the token-validity
rules, and the shape of the public payload. That put the one part of the app
reachable *without* a session entirely in the transport layer, where it was
also the hardest to test without going through HTTP.

Token validity is the security-relevant part and lives here, in one function,
so there is a single answer to "is this token still good".
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.hat import Hat
from headroom.models.user import ShareLink
from headroom.services.hat_service import hat_loads
from headroom.services.activity_service import log_and_commit

# 32 bytes -> 256 bits of entropy, url-safe. The token IS the credential for
# the public endpoints, so it has to be unguessable rather than merely unique.
from headroom.schemas.share import SharedColor, SharedHat
_TOKEN_BYTES = 32


class ShareLinkInvalid(Exception):
    """Token missing, revoked, or expired.

    One exception for all three on purpose: the route turns it into an
    identical 404, so a caller cannot tell a revoked link from a token that
    never existed. Distinguishing them would confirm which guesses were once
    real.
    """


async def list_links(db: AsyncSession) -> list[ShareLink]:
    result = await db.execute(select(ShareLink).order_by(ShareLink.id.desc()))
    return list(result.scalars().all())


async def create_link(
    db: AsyncSession, *, label: str, expires_days: int | None
) -> ShareLink:
    link = ShareLink(
        token=secrets.token_urlsafe(_TOKEN_BYTES),
        label=label,
        expires_at=(
            datetime.now(timezone.utc) + timedelta(days=expires_days)
            if expires_days
            else None
        ),
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    await log_and_commit(
        db, kind="share.created", entity_type="share_link", entity_id=link.id,
        summary=f"Share link '{link.label}' created (exposes the full active collection)",
    )
    return link


async def revoke_link(db: AsyncSession, link_id: int) -> ShareLink | None:
    """Revoke by id. None when there is no such link."""
    link = await db.get(ShareLink, link_id)
    if link is None:
        return None
    link.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    await log_and_commit(
        db, kind="share.revoked", entity_type="share_link", entity_id=link.id,
        summary=f"Share link '{link.label}' revoked",
    )
    return link


async def resolve_token(db: AsyncSession, token: str) -> ShareLink:
    """The link a token refers to, if it is still usable. Raises otherwise.

    Naive `expires_at` values are read as UTC: SQLite has no timezone type, so
    a datetime written as aware comes back naive, and comparing it to an aware
    `now()` raises rather than expiring the link. Treating it as UTC matches
    what was stored.
    """
    result = await db.execute(select(ShareLink).where(ShareLink.token == token))
    link = result.scalar_one_or_none()
    if link is None or link.revoked_at is not None:
        raise ShareLinkInvalid
    if link.expires_at is not None:
        expires = link.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise ShareLinkInvalid
    return link


async def shared_hats(db: AsyncSession) -> list[Hat]:
    """Every hat a share link exposes: the active collection, in id order.

    Disposed hats are excluded — a share link shows what is on the shelf, and
    disposition metadata (what it sold for, who it went to) is nobody else's
    business.
    """
    result = await db.execute(
        select(Hat)
        .options(*hat_loads())
        .where(Hat.disposed_at.is_(None))
        .order_by(Hat.id)
    )
    return list(result.scalars().all())


async def shared_hat(db: AsyncSession, hat_id: int) -> Hat | None:
    """A single hat an outside viewer may see, or None.

    Re-checks `disposed_at` rather than trusting that the caller came from
    `shared_hats`: the id arrives straight from a URL on every route that uses
    this.

    Deliberately does NOT require a photo. It used to, because its only caller
    was the photo endpoint — but a hat with no photo is still a real hat in the
    collection, and a detail view that 404s on one would be hiding something
    that is plainly listed on the page you clicked from. Photo-ness is the
    photo route's business, and both photo routes check it themselves.

    Eager-loads what the projection reads. `db.get` returned a bare instance,
    and `room_name` walks `hat.case.room` — a relationship hop that raises
    rather than lazy-loading under asyncio.
    """
    result = await db.execute(
        select(Hat)
        .options(
            *hat_loads(),
        )
        .where(Hat.id == hat_id, Hat.disposed_at.is_(None))
    )
    return result.scalar_one_or_none()


def photo_variant(hat: Hat, variant: str | None) -> str:
    """Which stored file a public photo request gets: the thumbnail when it
    asks for one and the hat has one, the canonical cutout otherwise. One
    definition for both public routes, so neither can drift back to serving
    the full file to a grid."""
    if variant == "thumb" and hat.thumb_path:
        return hat.thumb_path
    return hat.photo_path


def to_shared_hat(hat: Hat, photo_url: str | None, thumb_url: str | None = None):
    """Project a Hat into the shape an outside viewer receives.

    The TYPE was shared between share links and the guest view from the start;
    the mapper was copied. That is the half that matters — a field added to
    `SharedHat` gets filled in at whichever call site the author happened to be
    looking at, and the other one keeps working, so the copy that fell behind
    would be the one exposed to strangers.

    `photo_url` is the caller's, because the two surfaces stream photos through
    different routes (a token path vs the guest path). It is the only thing
    that legitimately differs.
    """

    return SharedHat(
        id=hat.id,
        display_id=hat.display_id,
        brand=hat.brand,
        model_name=hat.model_name,
        style=hat.style,
        photo_url=photo_url,
        thumb_url=thumb_url,
        colors=[
            SharedColor(name=c.general_color or c.color_name, hex=c.hex_value)
            for c in (hat.colors or [])
        ],
        case=hat.case_display_id,
        room=hat.room_name,
    )
