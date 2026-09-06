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

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.hat import Hat
from headroom.schemas.hat import KNOWN_CONSTRUCTIONS, strip_constructions
from headroom.services import retail_pricing, vocabulary


from headroom.models.activity_log import ActivityLog
@dataclass
class ConstructionCount:
    construction: str
    hat_count: int
    #: How many of those carry a retail price that came from the price table —
    #: i.e. a price derived from this construction rather than checked.
    priced_from_table: int


@dataclass
class ClearReport:
    """What reassigning a construction did, or would do under `dry_run`."""

    construction: str
    dry_run: bool
    #: What the matched hats become. None clears the field.
    to: str | None = None
    hats_cleared: int = 0
    model_names_corrected: int = 0
    prices_cleared: int = 0
    manual_prices_kept: int = 0
    #: Hats skipped because the activity log proves the OWNER set this value.
    owner_set_skipped: int = 0
    #: Display ids (or "#id" when unassigned), for the confirmation screen.
    samples: list[str] = field(default_factory=list)


async def owner_set_hat_ids(db: AsyncSession) -> set[int]:
    """Hats whose construction the OWNER demonstrably set, per the audit log.

    `hat_service.update_hat` writes a `hat.updated` row listing the fields a
    client PUT changed, so a row naming `construction` is proof a person typed
    it. That is the only durable evidence in the database: nothing else records
    where a construction came from, and analysis wrote the column directly.

    Two limits worth stating plainly, because this decides what a bulk
    reassignment leaves alone:

    * **Activity rows are pruned** (`HEADROOM_ACTIVITY_LOG_RETENTION_DAYS`,
      90 by default), so an edit older than the window is no longer provable.
    * **Creation-time values are not recorded.** `hat.created` logs style and
      size, not construction, so a construction typed into the Add form does
      not appear here.

    So this is a *proof of ownership*, not a complete one: it can say "this one
    is definitely yours", never "this one is definitely not". Which is exactly
    the right asymmetry for skipping — it only ever protects more, never less.
    """

    rows = (
        await db.execute(
            select(ActivityLog.entity_id).where(
                ActivityLog.kind == "hat.updated",
                ActivityLog.entity_type == "hat",
                # `details` is JSON-in-Text; the changed-field list is in there
                # verbatim. A `previous` map for the same edit also names it,
                # and either way it means a person changed this field.
                ActivityLog.details.like('%"construction"%'),
            )
        )
    ).scalars().all()
    return {r for r in rows if r is not None}


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
    db: AsyncSession,
    value: str,
    *,
    to: str | None = None,
    dry_run: bool = True,
    skip_owner_set: bool = True,
) -> ClearReport:
    """Reassign `value` to `to` (or clear it) on every active hat carrying it.

    Matched case-insensitively, because the stored spelling is whatever was
    written at the time and the caller is picking from a list, not typing.

    `to` exists because "these are all actually HYDRO" is the common case, and
    clearing them would throw away a correction the owner already knows how to
    make. Passing `to` writes the right answer instead of a blank; passing None
    clears, which is right when the truth is genuinely unknown.

    `skip_owner_set` protects values the owner demonstrably typed — see
    `owner_set_hat_ids` for what "demonstrably" can and cannot cover. It is on
    by default: this is a bulk write over a whole collection, and the cost of
    wrongly skipping one hat (fix it by hand) is far below the cost of wrongly
    overwriting one (you don't find out).
    """
    report = ClearReport(construction=value, dry_run=dry_run, to=to)
    target = value.strip().casefold()
    if not target:
        return report

    # A typed replacement goes through the vocabulary like every other
    # construction write (`hat_service`, the pipeline): `to="hydro"` stamped
    # dozens of rows with a spelling the record already held as `HYDRO`, which
    # is exactly the five-spellings-of-one-thing split `canonicalize` exists
    # to prevent — and this is the one writer that touches a whole shelf.
    if to:
        to = await vocabulary.canonicalize(db, Hat.construction, to, known=KNOWN_CONSTRUCTIONS)
        report.to = to

    protected = await owner_set_hat_ids(db) if skip_owner_set else set()
    hats = (await db.execute(select(Hat).where(Hat.disposed_at.is_(None)))).scalars().all()

    for hat in hats:
        if not hat.construction or hat.construction.casefold() != target:
            continue

        if hat.id in protected:
            report.owner_set_skipped += 1
            continue

        report.hats_cleared += 1
        if len(report.samples) < 10:
            report.samples.append(hat.display_id or f"#{hat.id}")

        # Strip the OLD construction out of the name either way; when `to` is
        # given the name is left less specific rather than rewritten, because
        # "A-Game HYDRO" would be inventing the product name back — the same
        # remove-don't-substitute rule the pipeline follows.
        corrected = strip_constructions(hat.model_name)
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

        hat.set_construction(to)
        hat.model_name = corrected
        if from_table:
            # The old price was looked up FROM the construction being replaced,
            # so it has to be recomputed rather than kept. With a `to` the table
            # usually has an answer (HYDRO → $79); with a clear it does not, and
            # inventing one is what this whole change exists to stop.
            price, source = retail_pricing.resolve_retail(
                hat.style,
                to,
                estimate=None,
                current=None,
                current_source=None,
            )
            hat.estimated_new_price = price
            hat.estimated_new_price_source = source

    if not dry_run:
        await db.commit()
    return report
