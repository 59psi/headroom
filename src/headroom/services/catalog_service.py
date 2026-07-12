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

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.catalog import ColorwayEntry, Purchase
from headroom.models.hat import Hat
from headroom.services.melin_recap import _STYLE_TO_CATEGORY, _query_listings

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


async def harvest_catalog(db: AsyncSession) -> dict:
    """Sweep every category; upsert unique titles. Returns counts."""
    now = datetime.now(timezone.utc)
    seen_titles = 0
    new_entries = 0

    for category in _STYLE_TO_CATEGORY.values():
        for page in range(1, _MAX_PAGES_PER_CATEGORY + 1):
            listings = await _query_listings(
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
                seen_titles += 1
                result = await db.execute(
                    select(ColorwayEntry).where(ColorwayEntry.title == title)
                )
                row = result.scalar_one_or_none()
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
                    new_entries += 1
                else:
                    row.listing_count += 1
                    row.last_seen = now
            await db.commit()
            if len(listings) < _PER_PAGE:
                break

    total = (await db.execute(select(func.count(ColorwayEntry.id)))).scalar_one()
    logger.info(
        "Colorway harvest: %d titles seen, %d new, %d total in catalog",
        seen_titles, new_entries, total,
    )
    return {"titles_seen": seen_titles, "new_entries": new_entries, "catalog_total": total}


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


async def import_purchases(db: AsyncSession, items: list[dict]) -> dict:
    """Store purchase line items; dedupe on (order_ref, item_title, price)."""
    imported = 0
    skipped = 0
    for item in items:
        title = (item.get("item_title") or "").strip()
        if not title:
            skipped += 1
            continue
        dupe = await db.execute(
            select(Purchase).where(
                Purchase.item_title == title,
                Purchase.order_ref == item.get("order_ref"),
                Purchase.price == item.get("price"),
            )
        )
        if dupe.scalar_one_or_none() is not None:
            skipped += 1
            continue
        model, colorway = parse_listing_title(title)
        order_date = None
        if item.get("order_date"):
            try:
                order_date = datetime.fromisoformat(str(item["order_date"]))
            except ValueError:
                pass
        db.add(
            Purchase(
                source=item.get("source", "email"),
                order_ref=item.get("order_ref"),
                order_date=order_date,
                item_title=title,
                model_name=model,
                colorway=colorway,
                price=item.get("price"),
                quantity=int(item.get("quantity", 1) or 1),
                raw=item.get("raw"),
            )
        )
        imported += 1
    await db.commit()
    return {"imported": imported, "skipped": skipped}


async def match_purchases_to_hats(db: AsyncSession) -> dict:
    """Link unmatched purchases to hats by model (+colorway when both have
    one) and set the hat's cost basis + colorway from the purchase."""
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
    for purchase in purchases:
        if not purchase.model_name:
            continue
        pm = purchase.model_name.lower()
        pc = (purchase.colorway or "").lower()
        for hat in hats:
            if hat.id in linked_hat_ids:
                continue
            hm = (hat.model_name or "").lower()
            hc = (hat.colorway or "").lower()
            if hm != pm:
                continue
            # If both sides know a colorway they must agree; a hat without
            # one accepts the purchase's.
            if hc and pc and hc != pc:
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
            break

    await db.commit()
    return {"matched": matched, "unmatched": len(purchases) - matched}
