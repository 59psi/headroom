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

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.hat import Hat

#: A source shared by MORE than this many hats is describing a line. One or two
#: hats sharing a number is ordinary — two examples of one product genuinely
#: cost the same. It takes a crowd before the number stops being about the hat.
#: Named for what it bounds (the unremarkable case) rather than for the crowd,
#: because `SHARED_THRESHOLD = 3` compared with `>` read as "three or more" and
#: meant four or more.
MAX_UNREMARKABLE = 3

#: The live listing count inside a source sentence, which is VOLATILE.
#:
#: The sentence reads "Melin Recap · median of 18 live classic new-with-tags
#: Odysea Rope Hydro listings", and that 18 is however many listings existed
#: the moment THAT hat took its turn. Re-pricing is sequential, paced a second
#: apart, oldest-first, and resumable — so hats priced against one line from
#: one median routinely carry different counts. Grouping on the raw sentence
#: therefore split the very cluster this report exists to reveal, into
#: fragments that each fell under the threshold and vanished entirely.
#:
#: Deliberately narrow: it neutralizes one integer in a fixed position and
#: leaves the rest of the sentence alone. The size and condition qualifiers are
#: stable facts about the hat, not about the moment, and they mark genuinely
#: different comparisons — CLAUDE.md's warning that branching on prose
#: "would silently revalue the collection the day someone reworded the label"
#: is the reason this does not try to parse the sentence apart.
#:
#: Same shape as `analysis_job_service._reason_key`: group on a cleaned key,
#: display the verbatim text.
_LIVE_COUNT = re.compile(r"(median of )\d+( live)")


def source_key(source: str | None) -> str:
    """The part of a source sentence that identifies the COMPARISON, not the run."""
    if not source:
        return ""
    return _LIVE_COUNT.sub(r"\1<n>\2", source)


@dataclass(frozen=True)
class HatRef:
    """One hat in a cluster: enough to name it, link it, and act on it.

    A single object rather than parallel `hat_ids` / `display_ids` lists. Those
    drifted, because a hat with no case has no `display_id` — the normal state
    for a room-stored or freshly-added hat — so the id list grew and the label
    list did not, and the card, indexing them side by side, drew one hat's
    shelf label on another hat's link.
    """

    hat_id: int
    display_id: str | None
    #: False is the actionable state: no colorway means no product can be
    #: named, and the owner is the only source for it.
    has_colorway: bool


@dataclass
class PriceCluster:
    """One price, and the hats that all carry it.

    Not named `SharedPriceGroup`: that is the pydantic schema this is mapped
    onto, and two different shapes under one name is a trap for whoever reads
    an import next.
    """

    resale_price: float
    #: A representative sentence, verbatim, as shown on those hats' pages. The
    #: cluster is keyed on `source_key()` of this, so members may differ in the
    #: live count this one happens to quote.
    source: str | None
    hats: list[HatRef] = field(default_factory=list)

    @property
    def hat_count(self) -> int:
        return len(self.hats)

    @property
    def missing_colorway(self) -> int:
        """How many carry no colorway — the actionable half."""
        return sum(1 for h in self.hats if not h.has_colorway)


async def audit(db: AsyncSession, threshold: int = MAX_UNREMARKABLE) -> list[PriceCluster]:
    """Active hats grouped by the price they share, biggest group first.

    `manual` prices are excluded: a number the owner typed is theirs, and two
    hats they priced the same are not a measurement error. Disposed hats are
    excluded because they have left the collection.

    Within a cluster, hats missing a colorway come first — they are the ones
    worth opening, and a truncated sample that led with the others would show
    the rows nothing can be done about.
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

    clusters: dict[tuple[float, str], PriceCluster] = {}
    for hat in rows:
        key = (hat.resale_price, source_key(hat.resale_price_source))
        cluster = clusters.setdefault(
            key,
            PriceCluster(resale_price=hat.resale_price, source=hat.resale_price_source),
        )
        # `display_id` walks `hat.case`, which is `lazy="selectin"`, so this
        # does not fire a lazy load mid-iteration. It is None for a hat with no
        # case — carried on the ref rather than dropped, so ids and labels
        # cannot fall out of step.
        cluster.hats.append(
            HatRef(
                hat_id=hat.id,
                display_id=hat.display_id,
                has_colorway=bool(hat.colorway),
            )
        )

    shared = [c for c in clusters.values() if c.hat_count > threshold]
    for cluster in shared:
        cluster.hats.sort(key=lambda h: (h.has_colorway, h.hat_id))
    return sorted(shared, key=lambda c: -c.hat_count)
