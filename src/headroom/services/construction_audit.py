"""Find and undo constructions that analysis guessed.

Until 2.32 the pipeline filled `construction` whenever the field was empty,
using Claude's read of the photo. That read is unreliable for exactly the
distinction that matters — HYDRO vs HYDROLite turns on bonded seams, a
gel-welded logo and a sweatband, none of which survive a front-on shot — and it
skewed toward HYDROLite. Analysis no longer writes the field at all, but the
values it already wrote are still in the database, and nothing recorded which
came from a person and which from a guess.

**There is no way to tell them apart retroactively**, so this module does not
try. It reports what is on record, and clears a value the owner names. That is
a decision only the person holding the hats can make, and the honest shape for
it is a preview plus an explicit action — not a startup backfill that silently
rewrites rows on the reasoning that most of them were probably wrong.

Clearing a construction also clears what was derived FROM it:

* the **retail price**, when it came from the price table. HYDROLite prices at
  $99 and HYDRO at $79, so a guessed HYDROLite carried a $20 premium that was
  never justified. Leaving that number behind while removing the reason for it
  is the worst of both — a price with no derivation, indistinguishable from one
  somebody checked. A manually entered price is never touched.
* the construction word inside **`model_name`**. melin names read
  "<line> <construction>", so "A-Game HYDROLite" asserts the same guess in the
  field a person actually reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.hat import Hat
from headroom.schemas.hat import KNOWN_CONSTRUCTIONS
from headroom.services import retail_pricing


@dataclass
class ConstructionCount:
    construction: str
    hat_count: int
    #: How many of those carry a retail price that came from the price table —
    #: i.e. a price derived from this construction rather than checked.
    priced_from_table: int


@dataclass
class ClearReport:
    """What clearing a construction did, or would do under `dry_run`."""

    construction: str
    dry_run: bool
    hats_cleared: int = 0
    model_names_corrected: int = 0
    prices_cleared: int = 0
    manual_prices_kept: int = 0
    #: Display ids (or "#id" when unassigned), for the confirmation screen.
    samples: list[str] = field(default_factory=list)


def _strip_constructions(model_name: str | None) -> str | None:
    """Remove every known construction word from a model name."""
    if not model_name:
        return model_name
    cleaned = model_name
    for known in KNOWN_CONSTRUCTIONS:
        cleaned = re.sub(rf"\b{re.escape(known)}\b", " ", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()) or None


async def audit(db: AsyncSession) -> list[ConstructionCount]:
    """Every construction on record, most common first."""
    hats = (await db.execute(select(Hat).where(Hat.disposed_at.is_(None)))).scalars().all()

    tally: dict[str, list[Hat]] = {}
    for hat in hats:
        if hat.construction:
            tally.setdefault(hat.construction, []).append(hat)

    rows = [
        ConstructionCount(
            construction=value,
            hat_count=len(group),
            priced_from_table=sum(
                1 for h in group
                if h.estimated_new_price_source == retail_pricing.TABLE_SOURCE
            ),
        )
        for value, group in tally.items()
    ]
    rows.sort(key=lambda r: (-r.hat_count, r.construction.lower()))
    return rows


async def clear_construction(
    db: AsyncSession, value: str, *, dry_run: bool = True
) -> ClearReport:
    """Clear `value` from every active hat carrying it.

    Matched case-insensitively, because the stored spelling is whatever was
    written at the time and the caller is picking from a list, not typing.
    """
    report = ClearReport(construction=value, dry_run=dry_run)
    target = value.strip().casefold()
    if not target:
        return report

    hats = (await db.execute(select(Hat).where(Hat.disposed_at.is_(None)))).scalars().all()

    for hat in hats:
        if not hat.construction or hat.construction.casefold() != target:
            continue

        report.hats_cleared += 1
        if len(report.samples) < 10:
            report.samples.append(hat.display_id or f"#{hat.id}")

        corrected = _strip_constructions(hat.model_name)
        if corrected != hat.model_name:
            report.model_names_corrected += 1

        # A price the owner entered is theirs and survives, exactly as
        # `resolve_retail` already guarantees against analysis.
        manual = hat.estimated_new_price_source == retail_pricing.MANUAL_SOURCE
        from_table = hat.estimated_new_price_source == retail_pricing.TABLE_SOURCE
        if manual:
            report.manual_prices_kept += 1
        elif from_table:
            report.prices_cleared += 1

        if dry_run:
            continue

        hat.set_construction(None)
        hat.model_name = corrected
        if from_table:
            # The table's answer depended on the construction being real. With
            # it gone there is nothing to look the price up by, and inventing
            # one is what this whole change exists to stop.
            hat.estimated_new_price = None
            hat.estimated_new_price_source = None

    if not dry_run:
        await db.commit()
    return report
