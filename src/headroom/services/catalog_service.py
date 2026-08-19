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
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.catalog import ColorwayEntry, Purchase
from headroom.models.hat import Hat
from headroom.services.activity_service import log_and_commit
from headroom.services.melin_recap import (
    STYLE_TO_CATEGORY,
    MelinRecapError,
    query_listings,
)

logger = logging.getLogger(__name__)

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
    result was a SILENTLY partial catalogue: the endpoint had already returned
    202, and nothing recorded that the run stopped early. A collection missing
    two thirds of its models looked exactly like a complete one.
    """
    now = datetime.now(timezone.utc)
    seen_titles = 0
    new_entries = 0
    failed: list[str] = []

    for category in STYLE_TO_CATEGORY.values():
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
        "entries": entries,
        "models": models,
        "colorways": colorways,
        "last_harvest": last_seen.isoformat() if last_seen else None,
    }


async def catalog_options(
    db: AsyncSession, q: str | None = None, model: str | None = None, limit: int = 25
) -> list[dict]:
    """Autocomplete: distinct models, or colorways for a given model."""
    if model:
        stmt = (
            select(ColorwayEntry.colorway, func.max(ColorwayEntry.listing_count))
            .where(
                func.lower(ColorwayEntry.model_name) == model.strip().lower(),
                ColorwayEntry.colorway.is_not(None),
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
    # model with no colourway, which then can't disambiguate anything.
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
    treats it as a wildcard, which is the pre-2.19 behaviour. Returning a
    made-up value instead would be worse than returning nothing, because a
    wrong size actively prevents the correct match rather than merely failing
    to sharpen it.
    """
    if not raw:
        return None
    key = raw.strip().lower().replace("-", "").replace(" ", "").replace("_", "")
    return _SIZE_ALIASES.get(key)


async def preview_import(db: AsyncSession, items: list[dict]) -> dict:
    """What `import_purchases` + matching WOULD do. Writes nothing.

    Deliberately does not go through `import_purchases` and roll back: this
    runs against a live database, and a transaction that inserts a hundred rows
    and then reverses them is one stray commit — anywhere down the call stack —
    away from being a real import nobody asked for. Everything here is built in
    memory and never added to the session.
    """
    hats = (
        (await db.execute(select(Hat).where(Hat.disposed_at.is_(None))))
        .scalars().all()
    )
    claimed = {
        p.hat_id for p in
        (await db.execute(select(Purchase).where(Purchase.hat_id.is_not(None)))).scalars().all()
    }

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

    proposals: list[dict] = []
    for purchase in would_import:
        candidates = [
            (score, hat)
            for hat in hats
            if hat.id not in claimed
            and (score := _match_score(purchase, hat)) is not None
        ]
        if not candidates:
            continue
        best_score = max(score for score, _ in candidates)
        best = [hat for score, hat in candidates if score == best_score]
        hat = best[0]
        claimed.add(hat.id)
        proposals.append({
            "item_title": purchase.item_title,
            "order_ref": purchase.order_ref,
            "price": purchase.price,
            "size": purchase.size,
            "hat_id": hat.id,
            "hat_display_id": hat.display_id,
            "score": best_score,
            "matched_on": _matched_on(purchase, hat),
            "ambiguous": len(best) > 1,
            "tied_hat_ids": [h.id for h in best] if len(best) > 1 else [],
            "sets_price": purchase.price is not None and hat.purchase_price is None,
        })

    return {
        "dry_run": True,
        "would_import": len(would_import),
        "duplicates": duplicates,
        "unusable": unusable,
        "likely_accessories": accessories,
        "would_match": len(proposals),
        "would_not_match": len(would_import) - len(proposals),
        "ambiguous": sum(1 for p in proposals if p["ambiguous"]),
        "proposals": proposals,
    }


def _looks_like_headwear(purchase: Purchase, hats: list[Hat]) -> bool:
    """Rough flag for lines that are not hats — travel cases, gift cards.

    Advisory only, and reported rather than acted on: an order line this does
    not recognise is still imported, because a heuristic that silently drops
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


def _match_score(purchase: Purchase, hat: Hat) -> int | None:
    """How well one hat fits one purchase. Higher is better; None = no match.

    Model name is mandatory. Colourway and size each *rule a hat out* when both
    sides state one and they disagree, and otherwise add to the score when they
    agree — so a stated-and-matching field beats a silent one, and neither is
    required. Scoring rather than first-hit is the point: the old matcher took
    whichever hat came back first, so with two sizes of one model on the shelf
    a Small could be handed the price of a Classic and nothing downstream ever
    looked wrong, because both hats ended up with *a* cost basis.
    """
    if not purchase.model_name:
        return None
    if (hat.model_name or "").lower() != purchase.model_name.lower():
        return None

    score = 1

    pc = (purchase.colorway or "").lower()
    hc = (hat.colorway or "").lower()
    if pc and hc:
        if pc != hc:
            return None
        score += 2

    ps, hs = purchase.size, hat.size
    if ps and hs:
        if ps != hs:
            return None
        score += 4  # outranks colourway: two sizes of one colourway is common

    return score


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
    hats = (
        (await db.execute(select(Hat).where(Hat.disposed_at.is_(None))))
        .scalars().all()
    )
    linked_hat_ids = {
        p.hat_id for p in
        (await db.execute(select(Purchase).where(Purchase.hat_id.is_not(None)))).scalars().all()
    }

    matched = 0
    proposals: list[dict] = []
    for purchase in purchases:
        candidates = [
            (score, hat)
            for hat in hats
            if hat.id not in linked_hat_ids
            and (score := _match_score(purchase, hat)) is not None
        ]
        if not candidates:
            continue
        best_score = max(score for score, _ in candidates)
        best = [hat for score, hat in candidates if score == best_score]
        # A tie means the records genuinely cannot tell these hats apart (same
        # model, same colourway, same size). Taking one at random would be a
        # coin flip presented as a fact; the tie is reported instead so it can
        # be resolved by hand.
        ambiguous = len(best) > 1
        hat = best[0]

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
            "tied_hat_ids": [h.id for h in best] if ambiguous else [],
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
    and *a* colourway.
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
