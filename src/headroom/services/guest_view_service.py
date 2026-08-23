"""Guest view: browsing the collection without logging in.

A share link is a secret URL you hand to one person. This is the same
read-only, price-free view offered to anyone who reaches the login screen —
useful when the app is on a LAN and you want people in the house to be able to
look without an account.

Three properties hold it together, and all three are deliberate:

**Off by default.** Turning on unauthenticated read access to somebody's whole
collection is not a default anyone should acquire by upgrading. It is a switch
in Settings, and until it is thrown these endpoints behave exactly as if they
did not exist.

**404, not 403, when disabled.** A 403 confirms the feature is there and merely
switched off, which is a fact about a private install that a stranger has no
reason to learn. The endpoints are indistinguishable from unrouted paths.

**The same projection as share links.** `SharedHat` already exists and already
omits prices, purchase history, disposition, wear counts, analysis state and
owner notes — its docstring says why: returning the full model and trusting the
frontend not to render the rest is exactly how that leaks. A second projection
would be a second thing to keep in step, and the one that fell behind would be
the one exposed to strangers.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.hat import Hat
from headroom.services import settings_service

#: App-settings key. Absent or anything but "1" means disabled.
GUEST_VIEW_KEY = "guest_view_enabled"


async def is_enabled(db: AsyncSession) -> bool:
    """Whether guests may browse. Default False — see the module docstring."""
    return (await settings_service.get_setting(db, GUEST_VIEW_KEY)) == "1"


async def set_enabled(db: AsyncSession, enabled: bool) -> None:
    """Turn guest browsing on or off. Commits."""
    await settings_service.set_setting(db, GUEST_VIEW_KEY, "1" if enabled else None)


async def guest_hats(
    db: AsyncSession, query: str | None = None, color_scope: str = "major"
) -> list[Hat]:
    """The hats a guest can see, optionally narrowed by a search term.

    Delegates to the same two services the owner's own views use — the share
    link's collection listing, and the real search — rather than assembling a
    third query. Search is the half that would otherwise drift: a guest-only
    copy would quietly stop matching what the owner's search matches, and
    nobody would notice because nobody runs both.

    `room_id` is deliberately not accepted. Guest search is over the hats
    themselves; the owner's room filter takes an id from a caller who has seen
    the room list, which a guest has not.
    """
    from headroom.services import share_link_service
    from headroom.services.search_service import GUEST_SEARCH_LIMIT, search_hats

    if query and query.strip():
        # `public_fields_only` is the important half. Matching on a field the
        # caller cannot see turns search into an ORACLE for it: `?q=worn`
        # returns exactly the worn hats, so a guest could read every hat's
        # condition — and its size, collection and construction — by probing,
        # even though `SharedHat` withholds all four.
        #
        # The higher limit is the other half: the response reports its own
        # length as the match count, so a truncated list would make that count
        # a lie. That is the `len()`-of-a-capped-list mistake this codebase has
        # already made twice.
        return await search_hats(
            db,
            query.strip(),
            public_fields_only=True,
            color_scope=color_scope,
            limit=GUEST_SEARCH_LIMIT,
        )
    return await share_link_service.shared_hats(db)
