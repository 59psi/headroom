"""Colorway catalog harvesting + purchase-history import & matching.

Catalog source: melinrecap listing titles are "Model - Colorway" strings
("A-Game Hydro - Heather Grey"). Harvesting pages through every style
category on the marketplace API (same anonymous public-read access the
site's own frontend uses) and upserts unique titles. Sold-out drops keep
circulating on the resale market for years, so this recovers names that
melin.com no longer lists.

Purchases: structured line items (typically extracted from Melin order
emails) stored verbatim, then matched to hats by model+colorway to set the
cost basis (`purchase_price`, `purchased_at`) and fill `colorway`.
"""

from __future__ import annotations

import asyncio

import logging
from collections.abc import Sequence
from typing import NamedTuple
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.catalog import ColorwayEntry, Purchase
from headroom.models.hat import Hat
from headroom.schemas.hat import KNOWN_CONSTRUCTIONS
from headroom.services import sweep_progress
from headroom.services.activity_service import log_and_commit
from headroom.services.melin_recap import (
    STYLE_TO_CATEGORY,
    MelinRecapError,
    query_listings,
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
    return _harvest_claimed

_PER_PAGE = 100
_MAX_PAGES_PER_CATEGORY = 50  # safety backstop; ~5000 listings/category


def parse_listing_title(title: str) -> tuple[str, str | None]:
    """"A-Game Hydro - Heather Grey" → ("A-Game Hydro", "Heather Grey").

    Splits on the FIRST " - "; colorways legitimately contain slashes and
    hyphens ("Heather Ocean / Heather Charcoal"). No separator → whole
    string is the model, colorway unknown.
    """
    model, sep, colorway = title.partition(" - ")
    model, colorway = model.strip(), colorway.strip()
    if not sep or not colorway:
        return model, None
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
            return await query_listings(params)
        except MelinRecapError:
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
                "per_page": _PER_PAGE,
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
        if len(listings) < _PER_PAGE:
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

    # try/except/finally: this runs as a BackgroundTask behind a 202, so an exception
    # here reaches nobody. Leaving `running` true would make a crashed harvest
    # read as one still in flight, forever — the precise false signal the
    # progress record exists to remove.
    progress.begin(len(STYLE_TO_CATEGORY))
    # try/FINALLY, with the error recorded in `except` — see the same shape in
    # `repricing.reprice_once`. `except Exception` alone misses CancelledError
    # (a BaseException), which would leave a cancelled harvest reporting itself
    # as running forever.
    error: str | None = None
    try:
        return await _harvest(db, now)
    except Exception as exc:
        error = str(exc)[:300]
        raise
    finally:
        progress.finish(error=error)


async def _harvest(db, now) -> dict:
    seen_titles = 0
    new_entries = 0
    failed: list[str] = []
    for category in STYLE_TO_CATEGORY.values():
        progress.advance(category)
        try:
            seen, new = await _sweep_category(db, category, now)
        except MelinRecapError as exc:
            # Keep going. The next category is independent, and a partial
            # harvest that KNOWS it is partial beats one that doesn't.
            logger.warning("Colorway harvest: category %s failed: %s", category, exc)
            failed.append(category)
            await db.rollback()
            continue
        seen_titles += seen
        new_entries += new

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
        "finished_at": now.isoformat(),
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
        "entries": entries,
        "models": models,
        "colorways": colorways,
        "last_harvest": last_seen.isoformat() if last_seen else None,
    }


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
    """
    if model:
        tokens = [t for t in _model_tokens(model) if t]
        stmt = (
            select(ColorwayEntry.colorway, func.max(ColorwayEntry.listing_count))
            .where(
                ColorwayEntry.colorway.is_not(None),
                *[ColorwayEntry.model_name.ilike(f"%{token}%") for token in tokens]
                or [func.lower(ColorwayEntry.model_name) == model.strip().lower()],
            )
            .group_by(ColorwayEntry.colorway)
            .order_by(func.max(ColorwayEntry.listing_count).desc())
        )
        if q:
            stmt = stmt.where(ColorwayEntry.colorway.ilike(f"%{q}%"))
        rows = (await db.execute(stmt.limit(limit))).all()
        return [{"value": colorway} for colorway, _count in rows]

    stmt = (
        select(ColorwayEntry.model_name, func.count(ColorwayEntry.id))
        .group_by(ColorwayEntry.model_name)
        .order_by(func.count(ColorwayEntry.id).desc())
    )
    if q:
        stmt = stmt.where(ColorwayEntry.model_name.ilike(f"%{q}%"))
    rows = (await db.execute(stmt.limit(limit))).all()
    return [{"value": model_name} for model_name, _count in rows]


# --------------------------- purchases -------------------------------- #


def _line_fields(item: dict) -> tuple[str, str | None, str | None, int]:
    """(title, model, colorway, quantity) for one incoming line."""
    title = (item.get("item_title") or "").strip()
    model, colorway = parse_listing_title(title)
    # An explicit colorway beats one recovered from the title. Order lines
    # carry it separately ("Indigo Depth / Classic") and plenty of titles have
    # no " - " to split on at all -- "Odysea Hydro Indigo Depth" parses to a
    # model with no colorway, which then can't disambiguate anything.
    colorway = (item.get("colorway") or colorway) or None
    try:
        quantity = max(int(item.get("quantity", 1) or 1), 1)
    except (TypeError, ValueError):
        quantity = 1
    return title, model, colorway, quantity


async def _units_to_add(
    db: AsyncSession, item: dict, title: str, quantity: int, staged: dict[tuple, int]
) -> tuple[int, float | None, str | None]:
    """How many rows this order line still needs. Returns (wanted, price, size).

    Extracted because `import_purchases` and `preview_import` each had a
    byte-identical copy. CLAUDE.md promises "the preview predicts the import
    exactly"; with two copies that was a claim maintained by hand, and the
    dedupe key is exactly where it had already gone wrong once (a key without
    `size` collapsed a real order that bought one model in two sizes).

    `staged` is mutated: one order can list the same hat on two lines, and
    without carrying the batch's own decisions the second line's count would
    depend on whether a flush happened to have run.
    """
    price = item.get("price")
    size = normalize_size(item.get("size"))
    key = (item.get("order_ref"), title, price, size)
    # `no_autoflush` because this SELECT and `staged` count the same rows.
    #
    # `import_purchases` adds a Purchase per unit as it walks the batch, and
    # those sit pending in the session. Any query autoflushes them first — so
    # rows this very batch just staged came back as `existing` AND were
    # counted again in `staged`, and the line was subtracted twice. It needs
    # two lines of one order sharing order_ref, title, price and size, which
    # carts usually merge; when it did happen the import silently wrote fewer
    # hats than the preview promised. Preview and import share this function
    # precisely so they cannot disagree, and an incidental flush was quietly
    # making them disagree anyway.
    with db.no_autoflush:
        existing = len((await db.execute(
            select(Purchase).where(
                Purchase.item_title == title,
                Purchase.order_ref == item.get("order_ref"),
                Purchase.price == price,
                Purchase.size.is_(None) if size is None else Purchase.size == size,
            )
        )).scalars().all())
    wanted = max(quantity - existing - staged.get(key, 0), 0)
    staged[key] = staged.get(key, 0) + wanted
    return wanted, price, size


async def import_purchases(db: AsyncSession, items: list[dict]) -> dict:
    """Store purchase line items, one row per unit bought.

    A line reading "x 2" is two hats, and a hat is what a purchase gets
    matched to -- one row per line meant the second hat of every multi-buy
    silently never got a cost basis. In this collection's own order history
    that is nearly 40% of lines, so it is the common case rather than an edge
    one.

    Dedupe is therefore by COUNT rather than existence: re-importing the same
    order finds the two rows already there and adds nothing, while an order
    that genuinely contains two of the same hat still gets both.
    """
    imported = 0
    skipped = 0
    # Rows this batch has already decided to add, keyed the same way as the
    # dedupe. One order can list the same hat on two separate lines, and
    # without this the second line's count would depend on whether a flush
    # happened to have run — which is how the preview and the import came to
    # disagree by a row on the same input.
    staged: dict[tuple, int] = {}
    for item in items:
        title, model, colorway, quantity = _line_fields(item)
        if not title:
            skipped += 1
            continue

        wanted, price, size = await _units_to_add(db, item, title, quantity, staged)
        skipped += quantity - wanted

        order_date = None
        if item.get("order_date"):
            try:
                order_date = datetime.fromisoformat(str(item["order_date"]))
            except ValueError:
                pass

        for _ in range(wanted):
            db.add(
                Purchase(
                    source=item.get("source", "email"),
                    order_ref=item.get("order_ref"),
                    order_date=order_date,
                    item_title=title,
                    model_name=model,
                    colorway=colorway,
                    size=normalize_size(item.get("size")),
                    price=price,
                    # Always 1: the row IS one unit. The original line quantity
                    # is recoverable by counting rows in the order.
                    quantity=1,
                    raw=item.get("raw"),
                )
            )
            imported += 1
    await db.commit()
    return {"imported": imported, "skipped": skipped}


# How order lines spell sizes, mapped to the app's vocabulary. Order emails
# render the variant as the customer sees it ("Transit / Classic"), which is
# title-cased and occasionally abbreviated; `Hat.size` stores the enum value.
_SIZE_ALIASES: dict[str, str] = {
    "classic": "classic",
    "c": "classic",
    "standard": "classic",   # the pre-2.0 name for the same size
    "small": "small",
    "s": "small",
    "sm": "small",
    "xlarge": "x_large",
    "x_large": "x_large",
    "xl": "x_large",
    "extralarge": "x_large",
    "onesize": None,         # travel cases and accessories, not a hat size
}


def normalize_size(raw: str | None) -> str | None:
    """"Classic" / "X-Large" / "C" -> the `Hat.size` value, or None.

    None means "no usable size on this line" and is not a failure: matching
    treats it as a wildcard, which is the pre-2.19 behavior. Returning a
    made-up value instead would be worse than returning nothing, because a
    wrong size actively prevents the correct match rather than merely failing
    to sharpen it.
    """
    if not raw:
        return None
    key = raw.strip().lower().replace("-", "").replace(" ", "").replace("_", "")
    return _SIZE_ALIASES.get(key)


async def _matchable_hats(db: AsyncSession) -> list[Hat]:
    """Every hat a purchase could be matched to, colors eagerly loaded.

    One definition because the preview and the import must consider the same
    shelf; two copies of this query is two places for the disposed-hat filter
    or the `selectinload` to drift. The eager load is not optional — scoring
    reads `hat.colors`, and a lazy access under async raises
    `greenlet_spawn has not been called`.
    """
    return list(
        (await db.execute(
            select(Hat).options(selectinload(Hat.colors)).where(Hat.disposed_at.is_(None))
        ))
        .scalars().all()
    )


async def preview_import(db: AsyncSession, items: list[dict]) -> dict:
    """What `import_purchases` + matching WOULD do. Writes nothing.

    Deliberately does not go through `import_purchases` and roll back: this
    runs against a live database, and a transaction that inserts a hundred rows
    and then reverses them is one stray commit — anywhere down the call stack —
    away from being a real import nobody asked for. Everything here is built in
    memory and never added to the session.
    """
    hats = await _matchable_hats(db)
    claimed = {
        p.hat_id for p in
        (await db.execute(select(Purchase).where(Purchase.hat_id.is_not(None)))).scalars().all()
    }

    # Purchases ALREADY on record and still unmatched. Importing calls
    # `match_purchases_to_hats`, which matches every purchase with a null
    # hat_id — not only the ones this file adds — so a preview built from the
    # file alone describes a different operation than the one the button runs.
    #
    # That gap is not cosmetic. Against the real collection, previewing a
    # single new line reported "1 to import, 0 would match" and the import then
    # matched 144 and wrote 144 hat prices, which is exactly the "every price
    # on the shelf is now slightly wrong" this preview exists to prevent.
    backlog = (
        (await db.execute(select(Purchase).where(Purchase.hat_id.is_(None))))
        .scalars().all()
    )

    would_import: list[Purchase] = []
    duplicates = 0
    unusable = 0
    accessories = 0
    staged: dict[tuple, int] = {}   # mirrors `import_purchases`; see there

    for item in items:
        title, model, colorway, quantity = _line_fields(item)
        if not title:
            unusable += 1
            continue

        wanted, price, size = await _units_to_add(db, item, title, quantity, staged)
        duplicates += quantity - wanted

        for _ in range(wanted):
            # Mirrors the row expansion in `import_purchases`. A preview that
            # counted lines while the import counts units would under-report
            # exactly the multi-buys this is meant to surface.
            transient = Purchase(
                source=item.get("source", "email"),
                order_ref=item.get("order_ref"),
                item_title=title,
                model_name=model,
                colorway=colorway,
                size=normalize_size(item.get("size")),
                price=price,
                quantity=1,
            )
            if not _looks_like_headwear(transient, hats):
                accessories += 1
            would_import.append(transient)

    # Match the file's lines and the backlog together, exactly as the import
    # will — through the SAME `assign_purchases`. A preview that assigned
    # differently would under-report the matches the import then makes, and be
    # wrong in the one direction nobody checks.
    new_rows = {id(p) for p in would_import}
    proposals: list[dict] = []
    backlog_matches = 0
    to_match = [*backlog, *would_import]
    assignment = assign_purchases(to_match, [h for h in hats if h.id not in claimed])
    for purchase in to_match:
        found = assignment.get(id(purchase))
        if found is None:
            continue
        hat, best_score, ambiguous, tied_hat_ids = found
        claimed.add(hat.id)
        if id(purchase) not in new_rows:
            backlog_matches += 1
        proposals.append({
            "item_title": purchase.item_title,
            "order_ref": purchase.order_ref,
            "price": purchase.price,
            "size": purchase.size,
            "hat_id": hat.id,
            "hat_display_id": hat.display_id,
            "score": best_score,
            "matched_on": _matched_on(purchase, hat),
            "ambiguous": ambiguous,
            "tied_hat_ids": tied_hat_ids if ambiguous else [],
            "sets_price": purchase.price is not None and hat.purchase_price is None,
            # Which half of the click this row is. A caller showing only the
            # file's own lines would reproduce the bug this split exists to fix.
            "already_on_record": id(purchase) not in new_rows,
        })

    from_file = len(proposals) - backlog_matches
    return {
        "dry_run": True,
        "would_import": len(would_import),
        "duplicates": duplicates,
        "unusable": unusable,
        "likely_accessories": accessories,
        # Matches among the lines in the FILE — what the operator is choosing.
        "would_match": from_file,
        "would_not_match": len(would_import) - from_file,
        # Purchases already on record that this same click would also match.
        # Reported separately rather than folded in, because they are the part
        # nobody asked for and the part that writes prices onto hats.
        "would_match_backlog": backlog_matches,
        # What `match_purchases_to_hats` will report afterwards. The number the
        # preview is accountable for.
        "would_match_total": len(proposals),
        "ambiguous": sum(1 for p in proposals if p["ambiguous"]),
        "proposals": proposals,
    }


def _looks_like_headwear(purchase: Purchase, hats: list[Hat]) -> bool:
    """Rough flag for lines that are not hats — travel cases, gift cards.

    Advisory only, and reported rather than acted on: an order line this does
    not recognize is still imported, because a heuristic that silently drops
    purchases would hide a real hat behind a wording nobody anticipated. It
    exists so the preview can say "12 of these look like accessories" instead
    of leaving them to be noticed as odd rows months later.
    """
    title = (purchase.item_title or "").lower()
    if any(word in title for word in (
        "travel case", "gift card", "shipping protection", "sticker",
        "lanyard", "keychain", "tote",
    )):
        return False
    # A model name already on the shelf is strong evidence it is headwear.
    known_models = {(h.model_name or "").lower() for h in hats if h.model_name}
    return (purchase.model_name or "").lower() in known_models or bool(purchase.size)


#: Exact model-name agreement.
MODEL_EXACT = 8
#: The hat's model name is a token-SUBSET of the purchase's. Weaker, and
#: deliberately below every exact match, but a real signal.
MODEL_CONTAINED = 2

#: An exact hit only after removing the construction word from both sides.
#: Below a true `MODEL_EXACT` — the names are not literally the same — but
#: above `MODEL_CONTAINED`, because both sides named the same line rather than
#: one being a prefix of the other.
MODEL_EXACT_STRIPPED = 5

#: An owner-stated field (`artist_series`, `construction`) found in the title.
#: Deliberately below the 6-point gap between MODEL_EXACT and MODEL_CONTAINED:
#: an exact model hit must outrank a contained one that also carries a series,
#: or the generic-family match would beat the product the receipt names.
STATED_FIELD = 5
#: The receipt's colorway shares a word with the colors read off the photo.
#: Weakest signal here — the analyzer names a dominant color ("brown") where
#: melin names a product colorway ("Bone Brown"), so agreement is suggestive
#: and disagreement means nothing.
COLOR_WORD = 3

#: An owner-entered purchase price matching the receipt to the cent. Ranked
#: above every descriptive signal because it is the only one that is a FACT
#: rather than someone's words for a color — and high enough to carry a hat
#: whose colorway text disagrees, which is the case it was added for.
PRICE_EXACT = 6


#: Every word that is a CONSTRUCTION rather than a product line, lowercased and
#: split the way `_model_tokens` splits. Used to retry the model gate with the
#: construction removed — see `_model_tier`.
_CONSTRUCTION_TOKENS: frozenset[str] = frozenset(
    t
    for known in KNOWN_CONSTRUCTIONS
    for t in known.lower().replace("-", " ").split()
)


@lru_cache(maxsize=4096)
def _model_tokens(name: str | None) -> frozenset[str]:
    """Model name as a bag of comparable words.

    Hyphens split because "A-Game" and "a game" are the same product line, and
    a bare "-" is dropped so "Trenches Thermal - Camo" tokenizes like
    "Trenches Thermal Camo".

    Cached because matching is quadratic — every purchase is scored against
    every free hat, twice (once to rank scarcity, once to assign) — over a
    vocabulary of a few hundred distinct strings. Pure function of its
    argument, so the cache can only ever return what it would have computed.
    """
    raw = (name or "").lower().replace("-", " ")
    return frozenset(t for t in raw.split() if t)


def _color_words(hat: Hat) -> frozenset[str]:
    """Color words the analyzer read off this hat's own photo.

    Every hat has these (the cutout's dominant colors), where only the matched
    ones have a `colorway`. They break ties that nothing else can: two
    otherwise identical Trenches Icon Hydros, one black and one white, against
    receipts that name the colorway.
    """
    words: set[str] = set()
    for c in hat.colors or []:
        words |= set(_model_tokens(c.general_color))
        words |= set(_model_tokens(c.color_name))
    return frozenset(words)


def _model_tier(hat_model: str | None, purchase_model: str) -> int | None:
    """How well two model names agree, or None if they don't.

    Exact equality is not enough, and the reason is structural rather than a
    data-quality accident. A hat's `model_name` comes from Claude Vision
    reading a PHOTO, which cannot show the sub-line — so it lands on the
    generic family: "odysea hydro", "trenches thermal", "a-game hydro". The
    order email states the full product: "Odysea Packable Hydro", "Trenches
    Icon Infinite Thermal", "A-Game Icon Hydro". Under string equality none of
    those meet, and on this collection that was ~120 purchase units — over half
    the genuinely matchable ones — silently left with no cost basis.

    So a hat also matches when its tokens are a SUBSET of the purchase's: the
    photo saw less than the receipt knew, which is exactly the expected
    relationship. It scores far below an exact hit, so an exact candidate
    always wins and this only ever picks up hats nothing better claimed.

    The subset direction matters and is not symmetric. A hat named MORE
    specifically than the purchase ("Trenches Icon Mill Pinya" vs a receipt
    reading "Trenches Icon") would mean the photo knew something the receipt
    did not, which does not happen — and allowing it would let one generic
    receipt line claim any specific hat in the family.
    """
    hat_tokens = _model_tokens(hat_model)
    purchase_tokens = _model_tokens(purchase_model)
    if not hat_tokens or not purchase_tokens:
        return None
    if hat_tokens == purchase_tokens:
        return MODEL_EXACT
    if hat_tokens < purchase_tokens:
        return MODEL_CONTAINED

    # Retry with the CONSTRUCTION word removed from both sides.
    #
    # melin model names read `<line> <construction>` — "Eagle Denim" — but a
    # receipt is free to put that word in either half of the title, and it
    # splits on " - " into model and colorway. A real miss:
    #
    #     hat      "Eagle Denim"                 -> {eagle, denim}
    #     purchase "Eagle Mill Union - Hickory Denim"
    #              model half                    -> {eagle, mill, union}
    #
    # `denim` sits in the COLORWAY half, so containment failed and a hat with
    # the right line, series, size and price to the cent was ruled out before
    # anything else was scored. Stripping the construction leaves {eagle},
    # which is properly contained, and the construction still earns its
    # `STATED_FIELD` bonus below because that is matched against the WHOLE
    # title where the word actually is.
    #
    # This is narrower than widening the gate to the whole title, which was
    # tried and rejected up in `_match_score` for letting any Trenches hat
    # claim any Trenches line. Removing one known vocabulary word from both
    # sides cannot introduce a new line, only reveal that two names describe
    # the same one.
    hat_bare = hat_tokens - _CONSTRUCTION_TOKENS
    purchase_bare = purchase_tokens - _CONSTRUCTION_TOKENS
    # A name made ENTIRELY of construction words ("Hydro") strips to nothing,
    # and the empty set is a subset of everything — it would match the whole
    # shelf. Fall back to the strict comparison above rather than that.
    if not hat_bare or not purchase_bare:
        return None
    if hat_bare == purchase_bare:
        return MODEL_EXACT_STRIPPED
    if hat_bare < purchase_bare:
        return MODEL_CONTAINED
    return None


def _match_score(purchase: Purchase, hat: Hat) -> int | None:
    """How well one hat fits one purchase. Higher is better; None = no match.

    Model name is mandatory. Colorway and size each *rule a hat out* when both
    sides state one and they disagree, and otherwise add to the score when they
    agree — so a stated-and-matching field beats a silent one, and neither is
    required. Scoring rather than first-hit is the point: the old matcher took
    whichever hat came back first, so with two sizes of one model on the shelf
    a Small could be handed the price of a Classic and nothing downstream ever
    looked wrong, because both hats ended up with *a* cost basis.
    """
    if not purchase.model_name:
        return None

    # MODEL is the gate, and only the model. Everything else scores.
    #
    # Making series and construction part of the gate was tried and was worse:
    # a hat recorded as series "CAMO" against a receipt reading "Trenches Icon
    # Hydro - Camo" has its series word in the COLORWAY half of the title, not
    # the model half, so requiring containment threw the hat out entirely.
    # Widening the gate to the whole title would then let any Trenches hat
    # claim any Trenches line. Gate narrow, score wide.
    tier = _model_tier(hat.model_name, purchase.model_name)
    if tier is None:
        return None
    score = tier

    # Owner-stated fields — typed in by the person who owns the hat, and so the
    # most reliable thing on the record. Matched against the WHOLE title,
    # because melin puts the series in either half ("Trenches Links Hydro" vs
    # "Trenches Icon Hydro - Camo"). A bonus, never a veto: 102 hats have no
    # series recorded at all, and absence is not disagreement.
    title_tokens = _model_tokens(purchase.item_title)

    # A stated construction that CONTRADICTS the title rules the hat out.
    #
    # Necessary once `_model_tier` can match past the construction word: with
    # it stripped, "A-Game Thermal" and "A-Game Hydro" both reduce to
    # {a, game}, so a Thermal hat could otherwise be handed a Hydro receipt's
    # price when no Hydro hat was free. Same principle colorway and size
    # already follow — both sides stating something, and disagreeing, is the
    # one case where silence would be better than a guess. HYDROLite is
    # checked as its own token, so it does not read as a HYDRO.
    hat_construction = _model_tokens(hat.construction) & _CONSTRUCTION_TOKENS
    title_construction = title_tokens & _CONSTRUCTION_TOKENS
    if hat_construction and title_construction and not (hat_construction & title_construction):
        return None

    for stated in (hat.artist_series, hat.construction):
        tokens = _model_tokens(stated)
        if tokens and tokens <= title_tokens:
            score += STATED_FIELD

    # The colorway the receipt states, against the colors read off this hat's
    # own photo. Every hat has these, where only matched ones have a colorway,
    # so this is the one tiebreaker available on an unmatched shelf. Bonus
    # only: the analyzer names a dominant color ("brown"), melin names a
    # product colorway ("Bone Brown"), and plenty of pairs are both true
    # without sharing a word.
    pcw = _model_tokens(purchase.colorway)
    if pcw and (pcw & _color_words(hat)):
        score += COLOR_WORD

    # PRICE the owner typed off the receipt, against the receipt.
    #
    # The strongest evidence available and it was going unused. A colorway is a
    # DESCRIPTION — the analyzer invents them, and an owner types what the hat
    # looks like ("Navy Denium") rather than what melin called it ("Hickory
    # Denim"). A price entered by hand from an order confirmation is a fact,
    # and matching one to the cent is corroboration a spelling cannot outweigh.
    price_corroborates = (
        hat.purchase_price is not None
        and purchase.price is not None
        and abs(float(hat.purchase_price) - float(purchase.price)) < 0.005
    )
    if price_corroborates:
        score += PRICE_EXACT

    pc = (purchase.colorway or "").lower()
    hc = (hat.colorway or "").lower()
    if pc and hc:
        if pc != hc:
            # Normally a veto — two stated colorways that disagree are
            # different hats. NOT when the price corroborates: a real miss was
            # a hat recorded "Navy Denium" against "Eagle Mill Union - Hickory
            # Denim", same line, same series, same size, same $200.00, bought
            # the same week. Everything a receipt can prove agreed, and the one
            # field the owner had guessed at threw it out.
            if not price_corroborates:
                return None
        else:
            score += 2

    ps, hs = purchase.size, hat.size
    if ps and hs:
        if ps != hs:
            return None
        score += 4  # outranks colorway: two sizes of one colorway is common

    return score


class Assignment(NamedTuple):
    """One purchase's chosen hat, and how confident that choice is."""

    hat: Hat
    score: int
    #: More than one hat shared the top score — the records cannot tell them
    #: apart, so the tie is reported rather than silently broken.
    ambiguous: bool
    tied_hat_ids: list[int]


def _improve_by_swapping(
    candidates: dict[int, list[tuple[int, Hat]]],
    holder: dict[int, tuple[Purchase, Hat]],
) -> None:
    """Raise the total score of an assignment without changing its size.

    Ordering the purchases by evidence fixes who reaches a contended hat
    first, which handles the common shape. It does not make the result
    max-WEIGHT: Kuhn's optimizes cardinality, and among the many assignments
    of that same maximum size nothing was choosing the better-evidenced one.

    This closes the rest with the two moves that cannot lose a link:

    * **Swap** two matched pairs, `(p1,h1) + (p2,h2)` → `(p1,h2) + (p2,h1)`,
      when both new pairs are candidates and the total goes up. Two links
      before, two after.
    * **Relocate** a matched purchase onto a hat nobody holds, when that
      scores higher. One link before, one after.

    Both preserve cardinality exactly, so the maximum-matching guarantee that
    `test_matching_achieves_the_maximum_possible` proves is untouched — this
    can only improve the tiebreak. Run to fixpoint; each pass strictly
    increases an integer total that is bounded above, so it terminates.

    **This is not a proof of global weight-optimality**, and saying so matters
    given what this module has already been wrong about. A true max-weight
    maximum matching needs min-cost max-flow; 2-swaps reach a local optimum
    that is exact for the realistic contention shape (several receipt lines of
    one model competing for the same few hats) and can in principle miss an
    improvement that requires rotating three or more pairs at once.
    """
    score_of: dict[tuple[int, int], int] = {}
    for pid, scored in candidates.items():
        for sc, hat in scored:
            score_of[(pid, id(hat))] = sc

    def paired_score(purchase: Purchase, hat: Hat) -> int | None:
        return score_of.get((id(purchase), id(hat)))

    improved = True
    while improved:
        improved = False
        held = list(holder.items())

        # Relocate onto an unheld hat that scores better.
        for hid, (purchase, hat) in held:
            if holder.get(hid) != (purchase, hat):
                continue  # already moved in this pass
            current = paired_score(purchase, hat) or 0
            for sc, other in candidates[id(purchase)]:
                if sc <= current or id(other) in holder:
                    continue
                del holder[hid]
                holder[id(other)] = (purchase, other)
                improved = True
                break

        # Swap two held pairs when the pair of new edges scores higher.
        held = list(holder.items())
        for i, (h1, (p1, hat1)) in enumerate(held):
            for h2, (p2, hat2) in held[i + 1:]:
                if holder.get(h1) != (p1, hat1) or holder.get(h2) != (p2, hat2):
                    continue
                now = (paired_score(p1, hat1) or 0) + (paired_score(p2, hat2) or 0)
                a, b = paired_score(p1, hat2), paired_score(p2, hat1)
                if a is None or b is None or a + b <= now:
                    continue
                holder[h2] = (p1, hat2)
                holder[h1] = (p2, hat1)
                improved = True


def assign_purchases(
    purchases: Sequence[Purchase], hats: Sequence[Hat]
) -> dict[int, Assignment]:
    """The best assignment of hats to purchases, keyed on `id(purchase)`.

    MAXIMUM bipartite matching (Kuhn's augmenting paths), not greedy.

    Greedy — take each purchase's best free hat, scarcest purchase first — is
    only a heuristic, and it was measured leaving 3 real matches unclaimed on a
    294-line history the moment the scoring changed. The property it seemed to
    have was luck, and a scarcity ordering was the trick that bought it: put
    the constrained purchases first and hope nothing downstream starves. Hope
    is the wrong mechanism for "did this hat get its price".

    (That helper, `_by_scarcity`, outlived its caller by several releases. It
    had no call site at all, while this docstring, `CLAUDE.md` and a test
    docstring all described it as the thing carrying the result — the test
    going as far as to claim a sabotage check against a function that never
    ran. Deleted. The lesson is narrow and worth keeping: when an algorithm is
    replaced, the prose explaining the old one is the part that survives.)
    Augmenting paths simply do not have the failure — a later purchase can
    displace an earlier one and send it to another hat it also fits.
    Deterministic, and O(V·E), which at a few hundred rows is nothing.

    Candidates are visited in DESCENDING SCORE order, so among assignments of
    the same (maximum) size the better-evidenced pairings are taken first.
    Cardinality is what is guaranteed; the score ordering is the tiebreak.

    Returns `{id(purchase): Assignment}`. `ambiguous` marks a
    purchase whose top score was shared by more than one hat — the records
    genuinely cannot tell those apart, and a coin flip presented as a fact is
    the thing this whole module exists to avoid.
    """
    candidates: dict[int, list[tuple[int, Hat]]] = {}
    ambiguous: dict[int, bool] = {}
    tied: dict[int, list[int]] = {}
    for purchase in purchases:
        scored = [
            (score, hat)
            for hat in hats
            if (score := _match_score(purchase, hat)) is not None
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1].id))
        candidates[id(purchase)] = scored
        top = scored[0][0] if scored else None
        tied[id(purchase)] = [h.id for sc, h in scored if sc == top and h.id is not None]
        ambiguous[id(purchase)] = len(tied[id(purchase)]) > 1

    # Keyed on `id(hat)`, NOT `hat.id`. A transient row's primary key is still
    # None — `preview_import` scores unsaved Purchase and Hat objects — so
    # `hat.id` collapses every unsaved hat onto one bucket and the matching
    # silently returns one result for the whole shelf.
    holder: dict[int, tuple[Purchase, Hat]] = {}

    def augment(purchase: Purchase, seen: set[int]) -> bool:
        for _score, hat in candidates[id(purchase)]:
            if id(hat) in seen:
                continue
            seen.add(id(hat))
            current = holder.get(id(hat))
            if current is None or augment(current[0], seen):
                holder[id(hat)] = (purchase, hat)
                return True
        return False

    # BEST-EVIDENCED FIRST, then fewest candidates. Kuhn's guarantees maximum
    # CARDINALITY whatever order it runs in, so this ordering is free — and it
    # is not cosmetic. Among the many assignments of that same maximum size,
    # the one produced depends entirely on who claims a contended hat first,
    # and until now that was decided by candidate count and then by the order
    # the rows came out of the database. A receipt matching a hat on colorway,
    # size AND price to the cent lost the hat to a line that merely shared a
    # model name and happened to be listed earlier — writing that line's cost
    # basis onto the hat. Measured: a $999 purchase price stored where $79 was
    # provable. The scores existed the whole time and nothing consulted them
    # at this level.
    for purchase in sorted(
        purchases,
        key=lambda p: (
            -(candidates[id(p)][0][0] if candidates[id(p)] else 0),
            len(candidates[id(p)]),
        ),
    ):
        augment(purchase, set())

    _improve_by_swapping(candidates, holder)

    out: dict[int, Assignment] = {}
    for purchase, hat in holder.values():
        score = next(sc for sc, h in candidates[id(purchase)] if h is hat)
        out[id(purchase)] = Assignment(
            hat=hat,
            score=score,
            ambiguous=ambiguous[id(purchase)],
            tied_hat_ids=tied[id(purchase)],
        )
    return out


async def match_purchases_to_hats(db: AsyncSession, *, dry_run: bool = False) -> dict:
    """Link unmatched purchases to hats and set the hat's cost basis.

    `dry_run` reports exactly what would happen and writes nothing — worth
    having before a bulk import of years of order history, because matching
    mutates hats and there is no undo for "every price on the shelf is now
    slightly wrong".
    """
    purchases = (
        (await db.execute(select(Purchase).where(Purchase.hat_id.is_(None))))
        .scalars().all()
    )
    hats = await _matchable_hats(db)
    linked_hat_ids = {
        p.hat_id for p in
        (await db.execute(select(Purchase).where(Purchase.hat_id.is_not(None)))).scalars().all()
    }

    free_hats = [h for h in hats if h.id not in linked_hat_ids]
    assignment = assign_purchases(purchases, free_hats)

    matched = 0
    proposals: list[dict] = []
    for purchase in purchases:
        found = assignment.get(id(purchase))
        if found is None:
            continue
        hat, best_score, ambiguous, tied_hat_ids = found

        proposals.append({
            "purchase_id": purchase.id,
            "item_title": purchase.item_title,
            "order_ref": purchase.order_ref,
            "price": purchase.price,
            "hat_id": hat.id,
            "hat_display_id": hat.display_id,
            "score": best_score,
            "matched_on": _matched_on(purchase, hat),
            "ambiguous": ambiguous,
            "tied_hat_ids": tied_hat_ids if ambiguous else [],
            "sets_price": purchase.price is not None and hat.purchase_price is None,
            "sets_colorway": bool(purchase.colorway) and not hat.colorway,
        })

        if dry_run:
            # Claim the hat locally so the preview doesn't show one hat being
            # matched by three different purchases.
            linked_hat_ids.add(hat.id)
            matched += 1
            continue

        purchase.hat_id = hat.id
        linked_hat_ids.add(hat.id)
        if purchase.colorway and not hat.colorway:
            hat.colorway = purchase.colorway
        if purchase.price is not None and hat.purchase_price is None:
            hat.purchase_price = purchase.price
        if purchase.order_date is not None and hat.purchased_at is None:
            hat.purchased_at = purchase.order_date
        matched += 1

    if dry_run:
        # Nothing was written, but the identity map now holds mutated objects
        # if a future edit to this function forgets that. Expire so the next
        # read comes from the database rather than from this preview.
        db.expire_all()
        return {
            "dry_run": True,
            "matched": matched,
            "unmatched": len(purchases) - matched,
            "ambiguous": sum(1 for p in proposals if p["ambiguous"]),
            "proposals": proposals,
        }

    await db.commit()
    return {
        "matched": matched,
        "unmatched": len(purchases) - matched,
        "ambiguous": sum(1 for p in proposals if p["ambiguous"]),
    }


def _revert_hat_fields(purchase: Purchase, hat: Hat) -> list[str]:
    """Undo what THIS purchase wrote onto the hat. Returns the fields cleared.

    Each field is cleared only if it still holds the exact value the match
    put there. Anything edited since belongs to whoever edited it, and a
    reversal that overwrote a hand-typed price would be a worse bug than the
    mis-match it was undoing — the same class of silent clobber that made an
    automatic feed erase manual resale prices.
    """
    cleared = []
    if purchase.price is not None and hat.purchase_price == purchase.price:
        hat.purchase_price = None
        cleared.append("purchase_price")
    if purchase.order_date is not None and hat.purchased_at == purchase.order_date:
        hat.purchased_at = None
        cleared.append("purchased_at")
    if purchase.colorway and hat.colorway == purchase.colorway:
        hat.colorway = None
        cleared.append("colorway")
    return cleared


async def unmatch_purchase(db: AsyncSession, purchase_id: int) -> dict:
    """Break one purchase→hat link and put the purchase back in the pool.

    Exists because matching had no undo at all. It mutates hats, it runs over
    years of imported order history in one call, and `match_purchases_to_hats`
    only ever considers purchases with a NULL `hat_id` — so a wrong link was
    permanent and invisible, since the hat still ended up with *a* cost basis
    and *a* colorway.
    """
    purchase = await db.get(Purchase, purchase_id)
    if purchase is None:
        raise HTTPException(status_code=404, detail="Purchase not found")
    if purchase.hat_id is None:
        return {"unmatched": 0, "hat_id": None, "cleared": []}

    hat = await db.get(Hat, purchase.hat_id)
    cleared = _revert_hat_fields(purchase, hat) if hat else []
    hat_id = purchase.hat_id
    purchase.hat_id = None
    await db.commit()

    await log_and_commit(
        db, kind="purchase.unmatched", entity_type="purchase", entity_id=purchase_id,
        summary=f"Purchase #{purchase_id} unlinked from hat #{hat_id}",
        details={"hat_id": hat_id, "cleared": cleared},
    )
    return {"unmatched": 1, "hat_id": hat_id, "cleared": cleared}


async def unmatch_all_purchases(db: AsyncSession) -> dict:
    """Break every purchase→hat link. The 'that whole run was wrong' button.

    Leaves the purchase rows themselves alone — re-importing them is the
    expensive part, and the thing that was wrong is the matching, not the
    order history.
    """
    linked = (
        (await db.execute(select(Purchase).where(Purchase.hat_id.is_not(None))))
        .scalars().all()
    )
    hats = {
        h.id: h for h in
        (await db.execute(
            select(Hat).where(Hat.id.in_([p.hat_id for p in linked]))
        )).scalars().all()
    } if linked else {}

    cleared_total = 0
    for purchase in linked:
        hat = hats.get(purchase.hat_id)
        if hat is not None:
            cleared_total += len(_revert_hat_fields(purchase, hat))
        purchase.hat_id = None
    await db.commit()

    await log_and_commit(
        db, kind="purchase.unmatched_all", entity_type="purchase",
        summary=f"Unlinked {len(linked)} purchase(s) from their hats",
        details={"unmatched": len(linked), "fields_cleared": cleared_total},
    )
    return {"unmatched": len(linked), "fields_cleared": cleared_total}


def _matched_on(purchase: Purchase, hat: Hat) -> list[str]:
    """Which fields actually agreed, for the preview to show its working."""
    fields = ["model"]
    if purchase.colorway and hat.colorway:
        fields.append("colorway")
    if purchase.size and hat.size:
        fields.append("size")
    return fields


async def unclaimed_from_purchases(db: AsyncSession) -> dict:
    """What the existing purchase backlog would fill in, if matching were re-run.

    Matching is reachable only from an IMPORT — it runs at the end of one, and
    nowhere else on its own schedule. So every improvement to the matcher, and
    every re-analysis that finally gives a hat a `model_name`, creates pairs
    that nothing will ever look at again unless somebody happens to press
    "Re-run matching". Measured on the real collection: **17 colorways and 16
    purchase prices** were sitting in already-imported orders, unclaimed, while
    the shared-price report told the owner a colorway was something only they
    could supply. It was the app's own data.

    This is the same shape as the bug `repricing` documents — a useful
    operation reachable only from inside a bigger one, so it stops happening
    the moment nobody runs the bigger one.

    Derived from `match_purchases_to_hats(dry_run=True)` rather than restating
    its rule: a second implementation of "what would matching do" is a second
    thing to keep in step, and the one that drifts is the one making the offer.
    """
    result = await match_purchases_to_hats(db, dry_run=True)
    proposals = result["proposals"]
    return {
        # SQL-free but still a count of the WHOLE proposal set, never a
        # truncated sample — a low number here reads as "nothing to do".
        "colorways": len({p["hat_id"] for p in proposals if p["sets_colorway"]}),
        "prices": len({p["hat_id"] for p in proposals if p["sets_price"]}),
        #: Proposals the matcher itself flagged as tied. Reported, not hidden:
        #: applying them is still better than a line median, but the owner
        #: should know which ones were a coin toss between equal candidates.
        "ambiguous": sum(1 for p in proposals if p["sets_colorway"] and p["ambiguous"]),
    }


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
      of them accepted anything containing it, including `Camo Camo`.

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

    want_model = set(_model_tokens(model_name))
    want_colorway = set(_model_tokens(colorway))
    if not want_model or not want_colorway:
        return False

    rows = (
        await db.execute(
            select(ColorwayEntry.model_name, ColorwayEntry.colorway)
        )
    ).all()
    for cat_model, cat_colorway in rows:
        # The model is contained BY the catalog entry (a photo cannot show the
        # sub-line); the colorway must match it EXACTLY. Containment in either
        # direction on this half admits a colorway naming no product — see the
        # docstring, both directions have now been wrong once.
        if want_model <= set(_model_tokens(cat_model)) and (
            set(_model_tokens(cat_colorway)) == want_colorway
        ):
            return True
    return False
