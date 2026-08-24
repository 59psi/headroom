"""Physical tags: what a QR code or NFC tag on a hat or a case points at.

An NFC tag and a printed QR are the same feature wearing different hats: both
carry one URL and nothing else. So this module owns that URL — its shape, what
identifies each kind of thing, and which host it names — and the label sheets,
the detail pages and the SPA landing route all defer to it.

Two decisions here are load-bearing, and both come from the same fact: **you
cannot rewrite a sticker that is already on a hat.**

**A hat tag keys on `hat.id`, not `display_id`.** A hat's display id is derived
from its case and position (`AH-01-02`), so it changes the moment the hat moves
case — and it is `None` for an unassigned hat, which is exactly the state a hat
is in while you are standing there tagging it. A sticker printed with a display
id is wrong as soon as you reshuffle a shelf, and silently so: it still scans,
it just opens a different hat. `hat.id` never changes. This is the same reason
`utils/photo.export_derivative_path` names its files by id.

A **case** tag keys on `display_id`, because that is the opposite case: the
display id is *painted on the physical case*, it is a unique column rather than
a derived one, and it does not change. Keying a case on its database id would
make the printed label and the URL disagree for no benefit.

**Tags point at `/t/...`, not at the real page.** One level of indirection that
costs nothing today and cannot be added later. `/cases/AH-01` is a routing
detail of the current SPA; `/t/c/AH-01` is a promise. If the route table is
ever reorganized, the landing route absorbs it and forty stickers keep working.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from headroom.services import settings_service

# The app-settings key holding the host to write into tags.
TAG_BASE_URL_KEY = "tag_base_url"

HAT = "h"
CASE = "c"


def tag_path(kind: str, ident: str | int) -> str:
    """The site-relative path a tag points at, e.g. `/t/h/42`, `/t/c/AH-01`."""
    return f"/t/{kind}/{ident}"


def tag_url(base_url: str, kind: str, ident: str | int) -> str:
    """The absolute URL to print into a QR or write onto an NFC tag."""
    return f"{base_url.rstrip('/')}{tag_path(kind, ident)}"


async def get_tag_base(db: AsyncSession, fallback: str) -> tuple[str, str]:
    """Resolve the host tags should name. Returns `(base_url, source)`.

    `fallback` is normally the current request's own origin, which is right for
    a casual print but wrong to burn into hardware: browse to the Pi by IP once
    and every tag you write that afternoon says `http://192.168.1.50:8000`,
    which stops resolving the next time DHCP hands out a different lease. The
    tags do not report this — they just open nothing.

    So the host is configurable and, once set, wins over whatever you happened
    to be browsing at. `http://headroom.local:8000` is the answer for a LAN
    install, and survives the Pi changing address.
    """
    stored = await settings_service.get_setting(db, TAG_BASE_URL_KEY)
    if stored and stored.strip():
        return stored.strip().rstrip("/"), "settings"
    return fallback.rstrip("/"), "request"


async def set_tag_base(db: AsyncSession, base_url: str | None) -> None:
    """Set (or clear, with None/empty) the host written into tags. Commits."""
    cleaned = (base_url or "").strip().rstrip("/")
    await settings_service.set_setting(db, TAG_BASE_URL_KEY, cleaned or None)
