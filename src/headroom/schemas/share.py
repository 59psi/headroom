"""I/O models for share links — management and the public read-only view.

These were hand-built dicts in the route, which meant the one endpoint served
to people outside the household had no declared schema: nothing pinned which
fields leave the building, and nothing appeared in the OpenAPI document. For a
public surface that is the wrong place to be informal.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


#: Days a share link lasts when the caller does not say.
#:
#: The default was "never", which made the easiest thing to create the most
#: dangerous thing to create. A share link is unscoped and whole-collection:
#: every hat, with photos, and the room and case each one lives in. Forwarded
#: once, that is a permanent, room-by-room, photographed inventory of valuables
#: belonging to an address — and nothing expires it, so it stays live for as
#: long as the install does.
#:
#: 30 days rather than something shorter because the realistic use is showing
#: somebody the collection over a few weeks, and a link that dies mid-
#: conversation trains people to create permanent ones. `expires_days: null` is
#: still accepted and still means never; the change is only which one you get
#: by not deciding.
DEFAULT_SHARE_EXPIRY_DAYS = 30


class ShareLinkCreate(BaseModel):
    label: str = Field("Shared collection", max_length=80)
    #: Omitted → `DEFAULT_SHARE_EXPIRY_DAYS`. An explicit `null` → never
    #: expires, which is why this cannot simply default to the constant: those
    #: two have to stay distinguishable, and a plain default would collapse
    #: them.
    expires_days: int | None = Field(DEFAULT_SHARE_EXPIRY_DAYS, ge=1, le=365)


class ShareLinkRead(BaseModel):
    """A link as its owner sees it — includes the token, so never public."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    token: str
    label: str
    created_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    # Not a column: the path the token is used at. Built by the route, which is
    # the layer that knows the URL space.
    url_path: str


class ShareLinkCreated(BaseModel):
    """The subset returned on creation — enough to copy the link and no more."""

    id: int
    token: str
    url_path: str


class SharedColor(BaseModel):
    name: str
    hex: str


class SharedHat(BaseModel):
    """One hat as an outside viewer sees it.

    Deliberately a projection and not `HatRead`. Everything absent here is
    absent on purpose: prices, purchase history, disposition, wear counts,
    analysis state and error text are the owner's business. Returning the full
    model and trusting the frontend not to render the rest is exactly how that
    leaks.
    """

    id: int
    display_id: str | None
    brand: str | None
    model_name: str | None
    style: str
    photo_url: str | None
    #: The 320 px WebP the authenticated grids render, on the same public
    #: route with `?variant=thumb`. The shared and guest grids served the
    #: full 1200 px cutout per tile (~170 KB each) — about 40 MB per open of
    #: a "group chat" link on the real collection.
    thumb_url: str | None = None
    colors: list[SharedColor]
    case: str | None
    room: str | None


class SharedCollection(BaseModel):
    label: str
    hat_count: int
    hats: list[SharedHat]
