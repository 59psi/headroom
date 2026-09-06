"""Find and release prices that were marked "yours" by a bug rather than by you.

Until 2.57.0 the Edit Hat form sent `estimated_new_price` and `resale_price` on
**every** save, seeded from the loaded hat. `hat_service.update_hat` reads a
sent key as "a person typed this number" and stamps the price `manual`, which is
permanent: `retail_pricing.resolve_retail` returns it forever, and both
`refresh_melin_resale` and `_apply_resale_pointer` bail on it.

So editing a colorway, or a note, or a date silently relabeled a scraped
melinrecap median as *"Price you entered — used as given"* and froze it against
every future analysis. The number on screen never changed; only its meaning did.

2.57.0 fixed the write path. It did not — could not — repair what was already
written, and the release notes claimed the fix without saying so.

**There is no way to tell them apart retroactively.** Nothing records whether a
`manual` stamp came from someone typing a price or from the form resending one,
and the values are identical either way. So this module does not guess. It
reports what is on record and releases the hats the owner names, which is the
same shape — and for the same reason — as `construction_audit`.

Releasing a price does not delete it. It clears the SCOPE, which is what makes
the number immune, and lets the next analysis re-derive it from the live market
feed or the retail table. If the owner really did type that price, re-entering
it stamps it again.

One signal is worth surfacing, and it is only a hint: a hat whose `manual`
price sits beside a `resale_price_url` or a `resale_checked_at` was priced by
the marketplace at some point, so a `manual` stamp on top of that is more likely
to be the bug than a person. Reported, never acted on automatically.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.hat import Hat, ResaleScope
from headroom.services import retail_pricing

MANUAL_SCOPE = ResaleScope.MANUAL  # this module's name for it; the enum is the definition


@dataclass(frozen=True)
class FrozenPrice:
    """One hat carrying a price the analysis pipeline can no longer touch."""

    hat_id: int
    display_id: str | None
    model_name: str | None
    resale_price: float | None
    estimated_new_price: float | None
    #: True when the hat also carries marketplace provenance — a URL or a
    #: checked-at timestamp — which means it WAS priced by the feed before
    #: something stamped it manual. A hint that this one is the bug, not a
    #: person. Never acted on automatically.
    was_market_priced: bool


async def audit(db: AsyncSession) -> list[FrozenPrice]:
    """Every active hat whose price is frozen against future analysis."""
    rows = (
        await db.execute(
            select(Hat)
            .where(
                Hat.disposed_at.is_(None),
                (Hat.resale_price_scope == MANUAL_SCOPE)
                | (Hat.estimated_new_price_source == retail_pricing.MANUAL_SOURCE),
            )
            .order_by(Hat.id)
        )
    ).scalars().all()

    return [
        FrozenPrice(
            hat_id=h.id,
            display_id=h.display_id,
            model_name=h.model_name,
            resale_price=h.resale_price,
            estimated_new_price=h.estimated_new_price,
            was_market_priced=bool(h.resale_price_url or h.resale_checked_at),
        )
        for h in rows
    ]


async def release(
    db: AsyncSession,
    hat_ids: list[int] | None = None,
    *,
    market_priced_only: bool = False,
    dry_run: bool = True,
) -> list[FrozenPrice]:
    """Hand the named hats back to the live feed. Returns what was (or would be) released.

    `hat_ids=None` means every frozen hat, which is why `dry_run` defaults to
    True — the same protection `construction_audit.clear` has. `market_priced_only`
    narrows it to the hats carrying marketplace provenance, which is the subset
    most likely to have been stamped by the bug.

    The price VALUE is left alone. Only the scope and the source label are
    cleared, so the number stays visible until something better replaces it —
    a blank price would be a worse answer than a stale one.
    """
    candidates = await audit(db)
    if hat_ids is not None:
        wanted = set(hat_ids)
        candidates = [c for c in candidates if c.hat_id in wanted]
    if market_priced_only:
        candidates = [c for c in candidates if c.was_market_priced]

    if dry_run or not candidates:
        return candidates

    for row in candidates:
        hat = await db.get(Hat, row.hat_id)
        if hat is None:
            continue
        if hat.resale_price_scope == MANUAL_SCOPE:
            hat.resale_price_scope = None
            hat.resale_price_source = None
        if hat.estimated_new_price_source == retail_pricing.MANUAL_SOURCE:
            hat.estimated_new_price_source = None
    await db.commit()
    return candidates
