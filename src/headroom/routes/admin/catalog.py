"""Colorway catalog harvesting + purchase-history import/matching."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.models.catalog import Purchase
from headroom.schemas.admin import (
    CatalogRefreshStarted,
    CatalogStatus,
    PurchaseImport,
    PurchaseRead,
)
from headroom.services import catalog_service
from headroom.services.melin_recap import MelinRecapError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/colorways/status", response_model=CatalogStatus)
async def colorway_catalog_status(db: AsyncSession = Depends(get_db)):
    """What is actually in the catalog.

    Separate from `/api/meta/colorways`, which is an autocomplete feed and caps
    at its own default limit — reading `len()` of that as "models known" made
    the card report 25 forever, which is indistinguishable from a harvest that
    genuinely found 25.
    """
    return CatalogStatus(**await catalog_service.catalog_stats(db))


@router.post("/colorways/refresh", status_code=202, response_model=CatalogRefreshStarted)
async def refresh_colorway_catalog(background: BackgroundTasks):
    """Harvest melinrecap listing titles into the colorway catalog.

    Runs in the background and returns immediately. The harvest is up to 9
    categories x 50 pages of sequential external calls — minutes of work — and
    doing that inside the request meant an open connection long enough for any
    reverse proxy in front of this to time out first, on the one endpoint whose
    progress you cannot see. Every other long job in this app is already
    queued; this was the exception.
    """
    background.add_task(_harvest_in_background)
    return CatalogRefreshStarted()


async def _harvest_in_background() -> None:
    """Own session: the request's is closed by the time this runs."""
    from headroom.database import async_session

    try:
        async with async_session() as db:
            result = await catalog_service.harvest_catalog(db)
        logger.info("Colorway catalog refresh finished: %s", result)
    except MelinRecapError as exc:
        logger.warning("Colorway catalog refresh failed: %s", exc)
    except Exception:
        logger.exception("Colorway catalog refresh crashed")


@router.post("/purchases/import")
async def import_purchases(
    data: PurchaseImport,
    dry_run: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Store purchase line items (from order emails). Fields per item:
    item_title (required), order_ref, order_date (ISO), price, quantity, size,
    raw.

    `?dry_run=true` reports what WOULD be imported and matched and writes
    nothing. Importing runs the matcher, which mutates hats, and a bulk import
    of years of order history is exactly the case where seeing the proposed
    matches first is worth the extra round trip — there is no undo for it.
    """
    if dry_run:
        return await catalog_service.preview_import(db, data.items)
    result = await catalog_service.import_purchases(db, data.items)
    match = await catalog_service.match_purchases_to_hats(db)
    return {**result, **match}


@router.get("/purchases", response_model=list[PurchaseRead])
async def list_purchases(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(Purchase).order_by(Purchase.order_date.desc()))
    ).scalars().all()
    return list(rows)


@router.post("/purchases/match")
async def rematch_purchases(
    dry_run: bool = False, db: AsyncSession = Depends(get_db)
):
    """Re-run purchase→hat matching (e.g. after adding hats or colorways).

    `?dry_run=true` returns the proposed links without writing them.
    """
    return await catalog_service.match_purchases_to_hats(db, dry_run=dry_run)


# `unmatch-all` rather than `/purchases/unmatch`, and it is registered BEFORE
# the `{purchase_id}` route: a literal segment that can be read as an id is
# how `/api/hats/import` got shadowed once already.
@router.post("/purchases/unmatch-all")
async def unmatch_all(db: AsyncSession = Depends(get_db)):
    """Break every purchase→hat link, reverting the fields each one set.

    The purchase rows survive — re-importing years of order history is the
    expensive part, and what was wrong is the matching, not the orders.
    Re-run `/purchases/match` afterwards to redo it.
    """
    return await catalog_service.unmatch_all_purchases(db)


@router.post("/purchases/{purchase_id}/unmatch")
async def unmatch_one(purchase_id: int, db: AsyncSession = Depends(get_db)):
    """Break one purchase→hat link and return the purchase to the pool.

    Reverts `purchase_price`, `purchased_at` and `colorway` on the hat, but
    only where they still hold the value this purchase wrote — anything
    edited since belongs to whoever edited it.
    """
    return await catalog_service.unmatch_purchase(db, purchase_id)
