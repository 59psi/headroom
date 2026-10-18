"""melin's colorway catalog: harvested names, the picker, the validator.

Catalog source: melinrecap listing titles are "Model - Colorway" strings
("A-Game Hydro - Heather Grey"). Harvesting pages through every style
category on the marketplace API (same anonymous public-read access the
site's own frontend uses) and upserts unique titles. Sold-out drops keep
circulating on the resale market for years, so this recovers names that
melin.com no longer lists. Colorways on the owner's receipts count too
(`_bought_colorways`).

The receipts themselves — import, matching, linking — are `purchase_service`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Collection
from datetime import datetime, timezone

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.catalog import ColorwayEntry, Purchase

# `melin_recap` as a MODULE, and every name read through it at call time.
# `query_listings` is the single network seam (conftest stubs it for the whole
# suite), and a by-name import bound this module to the REAL function at
# import: whether the harvest saw the stub depended on which test imported
# this module first, and only the socket-level refusal stood between the
# harvest and the live marketplace.
from headroom.services import (
    melin_recap,
    naming,
    sweep_progress,
)

logger = logging.getLogger(__name__)

#: Live progress of a harvest. This endpoint returns 202 and runs in the
#: background, so before this its only trace was a log line — from the Settings
#: page a working harvest and a dead button looked identical.
progress = sweep_progress.SweepProgress()

#: Whether a harvest is queued or running. Same mechanism, and the same
#: reasoning, as `repricing._full_sweep_claimed` — which this endpoint went
#: without for three releases while its structurally identical sibling had it.
#:
#: The harvest commits per page and upserts on `title`, so two concurrent runs
#: interleave inserts of the same listing: one of them loses the race between
#: its own SELECT and its INSERT and dies on
#: `UNIQUE constraint failed: colorway_catalog.title`. That exception escapes
#: the per-category isolation the harvest is built around — the whole point of
#: which is that one bad category cannot abandon the rest — and because both
#: runs share `progress`, the bar then reads 100% with a SQL error behind it.
#:
#: Reachable by ordinary use, not just by an API client: the card re-enables
#: as soon as the 202 lands, so a second press a second later is a normal
#: thing for a person to do when nothing appears to have happened.
_harvest_claimed = False


def claim_harvest() -> bool:
    """Reserve the harvest slot. False when one is already queued or running.

    Check-and-set with no await between the two, so a second request cannot
    land in the middle. The claim is taken in the REQUEST, not in the task:
    a background task has not started when the response is sent, so a guard
    reading `progress.running` has a window where a harvest is queued and
    invisible — the bug this endpoint's sibling documents at length.
    """
    global _harvest_claimed
    if _harvest_claimed:
        return False
    _harvest_claimed = True
    return True


def release_harvest() -> None:
    """Free the slot. Must run in a `finally`, or one crashed harvest refuses
    every later press for the life of the process."""
    global _harvest_claimed
    _harvest_claimed = False


def harvest_in_flight() -> bool:
    """Claimed OR running — which is not the same as `progress.running`.

    The claim is taken in the request and `progress.begin()` runs inside the
    background task, so between the 202 landing and the task being scheduled
    there is a window where a harvest is reserved and `progress.running` is
    still false. The card polls status, sees an idle sweep, re-enables the
    button, and the next press is refused by a guard nothing had told it
    about — the same invisible-queued-work problem the claim itself exists to
    solve, moved one layer out to the thing displaying it.
    """
    return _harvest_claimed or progress.running


# Page size is `melin_recap.PAGE_SIZE`, read rather than restated: the
# harvest used to carry its own `_PER_PAGE = 100` AND send it under the wrong
# key (`per_page`; the Sharetribe parameter is `perPage`). The API ignored the
# unknown key and served its default page, which happened to be 100 — so the
# loop worked by coincidence, and a change to either side would have truncated
# every category to one page with nothing to say so, since termination is "a
# short page arrived".
_MAX_PAGES_PER_CATEGORY = 50  # safety backstop; ~5000 listings/category


def parse_listing_title(title: str, *, separated_only: bool = False) -> tuple[str, str | None]:
    """"A-Game Hydro - Heather Grey" → ("A-Game Hydro", "Heather Grey").

    `naming.split_model_colorway` with the model half guaranteed a string:
    colorways legitimately contain slashes and hyphens ("Heather Ocean /
    Heather Charcoal"), so only a SPACED separator splits, and a title melin
    wrote with an em dash now splits too (it used to land in the catalog as
    a model called `Trenches Hydro — Camo`). A title that names no model
    (`" - Black"`) is an empty model with no colorway, never a colorway
    filed under `""`. `separated_only`: see `naming.split_model_colorway`.
    """
    model, colorway = naming.split_model_colorway(title, separated_only=separated_only)
    if model is None:
        return "", None
    return model, colorway


async def _fetch_page(params: dict, attempts: int = 3) -> list[dict]:
    """One page, retried on a transient marketplace failure.

    `query_listings` raises on ANY non-200 — a 429, a 502, a timed-out
    connection. Those are the normal weather of a public API swept a thousand
    listings at a time, and before this a single one of them ended the whole
    harvest.
    """
    delay = 1.0
    for attempt in range(1, attempts + 1):
        try:
            return await melin_recap.query_listings(params)
        except melin_recap.MelinRecapError:
            if attempt == attempts:
                raise
            await asyncio.sleep(delay)
            delay *= 2
    return []  # unreachable; keeps the type checker honest


async def _sweep_category(db: AsyncSession, category: str, now) -> tuple[int, int]:
    """Harvest one category. Returns (titles_seen, new_entries)."""
    seen = new = 0
    for page in range(1, _MAX_PAGES_PER_CATEGORY + 1):
        listings = await _fetch_page(
            {
                "pub_category": category,
                "perPage": melin_recap.PAGE_SIZE,
                "page": page,
                "fields.listing": "title",
            }
        )
        for li in listings:
            title = ((li.get("attributes") or {}).get("title") or "").strip()
            if not title:
                continue
            seen += 1
            row = (await db.execute(
                select(ColorwayEntry).where(ColorwayEntry.title == title)
            )).scalar_one_or_none()
            if row is None:
                model, colorway = parse_listing_title(title)
                db.add(
                    ColorwayEntry(
                        title=title,
                        model_name=model,
                        colorway=colorway,
                        category=category,
                        listing_count=1,
                        last_seen=now,
                    )
                )
                new += 1
            else:
                row.listing_count += 1
                row.last_seen = now
        await db.commit()
        if len(listings) < melin_recap.PAGE_SIZE:
            break
    return seen, new


async def harvest_catalog(db: AsyncSession) -> dict:
    """Sweep every category; upsert unique titles. Returns counts.

    Each category is isolated. One failing category used to abandon every
    category after it — the sweep is sequential and commits as it goes, so the
    result was a SILENTLY partial catalog: the endpoint had already returned
    202, and nothing recorded that the run stopped early. A collection missing
    two thirds of its models looked exactly like a complete one.
    """
    now = datetime.now(timezone.utc)

    # try/except/finally: this runs as an `asyncio.create_task` behind a 202 (a
    # `BackgroundTask` until 2.76.0, when it started claiming a slot), so an
    # exception here reaches nobody. Leaving `running` true would make a crashed harvest
    # read as one still in flight, forever — the precise false signal the
    # progress record exists to remove.
    progress.begin(len(melin_recap.STYLE_TO_CATEGORY))
    # try/FINALLY, with the error recorded in `except` — see the same shape in
    # `repricing.reprice_once`. `except Exception` alone misses CancelledError
    # (a BaseException), which would leave a canceled harvest reporting itself
    # as running forever.
    error: str | None = None
    try:
        result = await _harvest(db, now)
        # What the card can see. A harvest in which EVERY category failed
        # used to finish "successfully": 202, a progress bar to 100%, the
        # log line saying `9 categor(y/ies) failed`, `progress.error` null,
        # and the card announcing "Harvest finished — the counts above are
        # current" over a catalog of zero entries. Failures were in the
        # result dict, which the background task hands to nobody.
        _last_failed_categories[:] = result["failed_categories"]
        if result["failed_categories"] and len(result["failed_categories"]) == len(
            melin_recap.STYLE_TO_CATEGORY
        ):
            error = (
                f"every category failed ({len(result['failed_categories'])} of "
                f"{len(melin_recap.STYLE_TO_CATEGORY)}) — the marketplace was unreachable; "
                "the catalog was not updated"
            )
        return result
    except Exception as exc:
        error = str(exc)[:300]
        raise
    finally:
        progress.finish(error=error)


#: Categories the LAST harvest could not read. Process-local like `progress`
#: (a harvest is minutes inside this process and dies with it); published on
#: `CatalogStatus` so a partial catalog says which parts are missing.
_last_failed_categories: list[str] = []


async def _harvest(db, now) -> dict:
    seen_titles = 0
    new_entries = 0
    failed: list[str] = []
    # One connection pool for the whole run — see `melin_recap.shared_client`.
    async with melin_recap.shared_client():
        for category in melin_recap.STYLE_TO_CATEGORY.values():
            progress.start_unit(category)
            try:
                seen, new = await _sweep_category(db, category, now)
            except Exception as exc:  # noqa: BLE001 — see below; NOT BaseException
                # Keep going. The next category is independent, and a partial
                # harvest that KNOWS it is partial beats one that doesn't.
                #
                # `Exception`, not `MelinRecapError`. Narrowing it to the API error
                # made the isolation cover only the failure that was in mind when
                # it was written, while the stated property is broader — one bad
                # category cannot abandon the rest — and anything else escaped and
                # killed the whole run: an `IntegrityError` from a racing harvest
                # (now prevented by the claim, but that is a second guard, not this
                # one), a disk error mid-commit, a decode failure on a title. The
                # narrow clause looked careful and was the reason a single bad
                # category could still lose eight good ones.
                #
                # `Exception` deliberately excludes `CancelledError`, which is a
                # `BaseException`: a shutdown must stop the sweep, not be absorbed
                # into `failed` and reported as one flaky category.
                logger.warning("Colorway harvest: category %s failed: %s", category, exc)
                failed.append(category)
                await db.rollback()
                progress.advance()  # a failed category is still a finished one
                continue
            seen_titles += seen
            new_entries += new
            progress.advance()

    total = (await db.execute(select(func.count(ColorwayEntry.id)))).scalar_one()
    models = (await db.execute(
        select(func.count(func.distinct(ColorwayEntry.model_name)))
    )).scalar_one()
    result = {
        "titles_seen": seen_titles,
        "new_entries": new_entries,
        "catalog_total": total,
        "distinct_models": models,
        "failed_categories": failed,
        # The END of the run, not `now`, which is when it began.
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(
        "Colorway harvest: %d titles seen, %d new, %d total (%d models), %d categor(y/ies) failed",
        seen_titles, new_entries, total, models, len(failed),
    )
    return result


async def catalog_stats(db: AsyncSession) -> dict:
    """What is actually IN the catalog — not a page of autocomplete options.

    The Settings card used to report `len(GET /api/meta/colorways)` as "models
    known". That endpoint is autocomplete and caps at `catalog_options`'s
    default limit, so the figure read 25 no matter how many models had been
    harvested — indistinguishable from a harvest that had found 25.
    """
    entries = (await db.execute(select(func.count(ColorwayEntry.id)))).scalar_one()
    models = (await db.execute(
        select(func.count(func.distinct(ColorwayEntry.model_name)))
    )).scalar_one()
    colorways = (await db.execute(
        select(func.count(func.distinct(ColorwayEntry.colorway)))
        .where(ColorwayEntry.colorway.is_not(None))
    )).scalar_one()
    last_seen = (await db.execute(select(func.max(ColorwayEntry.last_seen)))).scalar_one()
    return {
        "progress": progress.snapshot(),
        "in_flight": harvest_in_flight(),
        "failed_categories": list(_last_failed_categories),
        "entries": entries,
        "models": models,
        "colorways": colorways,
        "last_harvest": last_seen.isoformat() if last_seen else None,
    }


#: A catalog model name carrying any character outside printable ASCII.
_NON_ASCII_GLOB = "*[^ -~]*"


def _model_prefilter(tokens: Collection[str]) -> ColumnElement[bool]:
    """SQL narrowing for "the catalog model contains every token" — a SUPERSET.

    One `ILIKE '%token%'` per token decides the question for ASCII names. It
    cannot for the rest: `naming` folds accents (`Piña` → `pina`) and SQLite
    cannot, so `ILIKE '%pina%'` misses a stored `Piña` and the pre-filter would
    silently drop a row the token test accepts. Any name with a non-ASCII
    character is therefore passed through unfiltered, to be decided by the
    token test in Python like every other row. Such names are rare, which is
    what keeps the narrowing worth doing.
    """
    return or_(
        and_(*[ColorwayEntry.model_name.ilike(f"%{token}%") for token in tokens]),
        ColorwayEntry.model_name.op("GLOB")(_NON_ASCII_GLOB),
    )


async def _bought_colorways(
    db: AsyncSession, model: str | None, q: str | None = None
) -> dict[str, int]:
    """Colorways on the owner's own receipts for this model, with how many
    units of each — colorway knowledge the harvested catalog (marketplace
    listings) can lack, and the only kind that is certainly a real product.

    Same model rule as the catalog side — every requested token contained —
    through `naming.model_tokens`, because receipts spell the Odysea "Odyssey".
    Accessories are left out: a travel case's "Black" says nothing about a hat.
    """
    wanted = naming.model_tokens(model)
    if not wanted:
        return {}
    stmt = select(Purchase.item_title, Purchase.model_name, Purchase.colorway).where(
        Purchase.colorway.is_not(None)
    )
    if q:
        stmt = stmt.where(Purchase.colorway.ilike(f"%{q}%"))
    counts: dict[str, int] = {}
    for title, p_model, colorway in (await db.execute(stmt)).all():
        if naming.is_accessory(title) or not wanted <= naming.model_tokens(p_model):
            continue
        counts[colorway] = counts.get(colorway, 0) + 1
    return counts


async def catalog_options(
    db: AsyncSession, q: str | None = None, model: str | None = None, limit: int = 25
) -> list[dict]:
    """Autocomplete: distinct models, or colorways for a given model.

    Model matching is TOKEN CONTAINMENT, not equality, for the same reason
    `_match_score` uses `MODEL_CONTAINED`: a hat's `model_name` comes from
    Claude reading a PHOTO, which cannot show the sub-line, so it lands on the
    family (`odysea hydro`) while the catalog holds the product harvested from
    a listing title (`Odysea Packable Hydro`). Under equality those hats got
    ZERO colorways at any limit — the picker looked empty and the catalog
    looked incomplete, which is exactly how this was reported.

    Asymmetric on purpose, matching the matcher: every token of the requested
    model must appear in the catalog entry, so `odysea hydro` reaches
    `Odysea Packable Hydro`, but a request for the more specific name does not
    pull in the whole family.

    TOKENS, not substrings. This was written as one `ILIKE '%token%'` per
    token — which is substring containment, and `hydro` is a substring of
    `hydrolite`, so an `A-Game Hydro` hat was offered every HYDROLite colorway:
    the exact confusion `_rival_construction` and the HatFilters predicate both
    guard against by word boundary, in the one picker that writes the field.
    The SQL keeps the `ILIKE`s as a coarse pre-filter (a superset of the token
    match, and small), and the real test is `naming.token_set` containment in
    Python — the same rule `is_real_product` applies to the analyzer's answer.
    """
    if model:
        wanted = naming.token_set(model)
        stmt = select(
            ColorwayEntry.model_name, ColorwayEntry.colorway, ColorwayEntry.listing_count
        ).where(
            ColorwayEntry.colorway.is_not(None),
            _model_prefilter(wanted)
            if wanted
            else func.lower(ColorwayEntry.model_name) == model.strip().lower(),
        )
        if q:
            stmt = stmt.where(ColorwayEntry.colorway.ilike(f"%{q}%"))
        best: dict[str, int] = {}
        for entry_model, colorway, count in (await db.execute(stmt)).all():
            if wanted and not wanted <= naming.token_set(entry_model):
                continue
            best[colorway] = max(best.get(colorway, 0), int(count or 0))
        bought = await _bought_colorways(db, model, q)
        # What the owner actually bought of this model leads — on their own
        # receipts, so certainly real and the likeliest answer for a hat on
        # their shelf — then the harvested catalog by listing count.
        ranked = sorted(
            set(best) | set(bought),
            key=lambda c: (-bought.get(c, 0), -best.get(c, 0), c),
        )
        return [{"value": colorway} for colorway in ranked[:limit]]

    stmt = (
        select(ColorwayEntry.model_name, func.count(ColorwayEntry.id))
        .group_by(ColorwayEntry.model_name)
        .order_by(func.count(ColorwayEntry.id).desc())
    )
    if q:
        stmt = stmt.where(ColorwayEntry.model_name.ilike(f"%{q}%"))
    rows = (await db.execute(stmt.limit(limit))).all()
    return [{"value": model_name} for model_name, _count in rows]


async def is_real_product(db: AsyncSession, model_name: str | None, colorway: str | None) -> bool:
    """Does `<model_name> - <colorway>` name a product melin actually sells?

    The check that lets the analyzer's colorway be USED rather than trusted.
    Claude reads a colorway off the hat, which is a different act from
    inferring one from the photo's colors (measured at 12% precision) — but it
    is still a reading, and a wrong colorway prices the hat as somebody else's
    product. Validating against the harvested catalog turns the answer into a
    lookup: a colorway that survives this names a real good.

    Deliberately NOT done by handing Claude a candidate list. `_known_series_context`
    documents why — a menu invites a forced choice, and a wrong pick is
    indistinguishable from a right one. A validator applied afterwards has the
    opposite property: it can only ever reject.

    **The two halves need OPPOSITE asymmetries**, and containment on both was
    wrong in the direction that matters. Measured against a catalog holding
    only `Trenches Icon Hydro - Rain Camo`, subset-on-both accepted the
    colorways `Camo`, `Rain` and even `Rain` on a shortened model — none of
    which is a product melin sells. So the guard the whole feature rests on
    passed exactly the vague readings it exists to reject, while its own tests
    recorded that the real leaked colorways ("Hawaii 808 Camo") failed. It
    rejected the specific and accepted the vague.

    * **Model: hat tokens ⊆ catalog tokens.** `model_name` comes from a PHOTO,
      which cannot show the sub-line, so it lands on the family ("Odysea
      Hydro") where the catalog carries the product ("Odysea Packable Hydro").
      Same direction as `_model_tier`, for the same reason.
    * **Colorway: token-set EQUALITY.** This half was containment, in the
      direction that let a reading carry EXTRA words — and that is a leak the
      tests could not see. `{camo} ⊆ {hawaii, 808, camo}`, so a catalog holding
      `Odysea Rope Hydro - Camo` validated the colorway `Hawaii 808 Camo`,
      which names no product. It survived review because the fixture colorway
      was `Deep Dive`: at two tokens, containment happens to fail. **Single-word
      colorways are the common case** — Camo, Black, Navy, Bone — and every one
      of them accepted anything containing it.

      (An earlier draft of this paragraph cited `Camo Camo` as an example of
      what the fix rejects. Executed against the real function it still
      returns True, because the comparison is on token SETS and a repeated
      word collapses — harmless, since it names the same product, but it was a
      claim about behavior that the behavior did not support, inside the
      docstring of a function whose two previous versions were also confidently
      wrong. Removed rather than reworded: the honest example is a colorway
      carrying a word the catalog does not have at all.)

      That is not a cosmetic false positive. `_apply_analyzed_colorway` WRITES
      whatever survives, and a stored colorway is a VETO in `_match_score` — so
      a colorway invented here rules the hat out of its own receipt. The
      feature exists to make matching better and this made it worse.

      Equality is what the docstring above already promises: whatever survives
      names a real good. A reading that is vaguer than the catalog's name is
      not that product; a reading carrying a word the catalog does not have is
      not that product either. Both are now refused, and the ONLY asymmetry
      left is the model's, which is justified by the photo.
    """
    if not model_name or not colorway:
        return False

    want_model = set(naming.token_set(model_name))
    want_colorway = set(naming.token_set(colorway))
    if not want_model or not want_colorway:
        return False

    # Narrowed in SQL first — the same pre-filter `catalog_options` uses, a
    # superset of the token test below — so this no longer pulls the whole
    # catalog (568+ rows) into Python for every analyzed hat. The decision
    # itself is still made in Python, on tokens.
    rows = (
        await db.execute(
            select(ColorwayEntry.model_name, ColorwayEntry.colorway).where(
                ColorwayEntry.colorway.is_not(None),
                _model_prefilter(want_model),
            )
        )
    ).all()
    for cat_model, cat_colorway in rows:
        # The model is contained BY the catalog entry (a photo cannot show the
        # sub-line); the colorway must match it EXACTLY. Containment in either
        # direction on this half admits a colorway naming no product — see the
        # docstring, both directions have now been wrong once.
        if want_model <= set(naming.token_set(cat_model)) and (
            set(naming.token_set(cat_colorway)) == want_colorway
        ):
            return True
    # The owner's own receipts, under the same two rules. A colorway printed
    # on an order confirmation is a product melin sold, and the harvest — a
    # marketplace's live listings — can lack it entirely: an older or
    # sold-out colorway is exactly the kind on a collector's shelf and not on
    # a resale site. Equality on the colorway half, as above.
    for p_colorway in (await _bought_colorways(db, model_name)):
        if set(naming.token_set(p_colorway)) == want_colorway:
            return True
    return False
