"""Which prices describe a LINE rather than the hat they are printed beside?

The reported complaint was that resale values "are all very wrong". They were
not individually implausible — they were *identical*: measured on a real
collection, 168 of 235 hats carried one of just five numbers, 54 of them at
exactly $85.00. Nothing in the app said so. Each hat's page showed its own
figure with its own source sentence, and only an outside query over the whole
collection revealed that dozens shared one.

2.71.0 made pricing prefer melin's own product (`<Model> - <Colorway>`), which
splits a line into its real goods. But it can only do that for a hat whose
product can be identified, and for many it cannot. Measured on the real
collection:

  * 82 of 235 hats carry no colorway, so there is no product to name.
  * 59 of those 82 have no eligible purchase to inherit one from.
  * 47 of 76 have no candidate product on the marketplace AT ALL — their model
    is not currently listed, so there is nothing to pick even by hand.
  * Inferring a colorway from the photo's extracted colors was measured at
    **12% precision** (4 right, 28 wrong) against hats whose colorway is known,
    so guessing would confidently price 28 hats off somebody else's product —
    strictly worse than leaving it blank.

So for a large minority of hats a line median is genuinely the best available
signal, and the honest fix is not to invent precision but to SAY SO. This
groups active hats by the source sentence their price came from: a source
covering fifty hats is, by construction, not an appraisal of any one of them.

Reports only. Like `price_audit` and `construction_audit`, it changes nothing —
the owner is the one who knows which hat is which.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.hat import Hat

#: A source shared by more than this many hats is describing a line. One or two
#: hats sharing a number is ordinary — two examples of one product genuinely
#: cost the same. It takes a crowd before the number stops being about the hat.
SHARED_THRESHOLD = 3


@dataclass
class SharedPriceGroup:
    """One price, and the hats that all carry it."""

    resale_price: float
    source: str | None
    hat_ids: list[int] = field(default_factory=list)
    display_ids: list[str] = field(default_factory=list)
    #: How many of these carry no colorway. This is the actionable half: it is
    #: the missing colorway that prevents a product being named, and it is the
    #: one thing the owner can supply that nothing else can.
    missing_colorway: int = 0

    @property
    def hat_count(self) -> int:
        return len(self.hat_ids)


async def audit(db: AsyncSession, threshold: int = SHARED_THRESHOLD) -> list[SharedPriceGroup]:
    """Active hats grouped by the price they share, biggest group first.

    `manual` prices are excluded: a number the owner typed is theirs, and two
    hats they priced the same are not a measurement error. Disposed hats are
    excluded because they have left the collection.
    """
    rows = (
        await db.execute(
            select(Hat)
            .where(
                Hat.disposed_at.is_(None),
                Hat.resale_price.is_not(None),
                (Hat.resale_price_scope.is_(None))
                | (Hat.resale_price_scope != "manual"),
            )
            .order_by(Hat.id)
        )
    ).scalars().all()

    groups: dict[tuple[float, str | None], SharedPriceGroup] = {}
    for hat in rows:
        key = (hat.resale_price, hat.resale_price_source)
        g = groups.setdefault(
            key, SharedPriceGroup(resale_price=hat.resale_price, source=hat.resale_price_source)
        )
        g.hat_ids.append(hat.id)
        # `display_id` walks `hat.case`; these rows are loaded as entities so
        # the relationship is available, but a hat with no case has none.
        if hat.display_id:
            g.display_ids.append(hat.display_id)
        if not hat.colorway:
            g.missing_colorway += 1

    shared = [g for g in groups.values() if g.hat_count > threshold]
    return sorted(shared, key=lambda g: -g.hat_count)
