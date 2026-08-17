"""Colorway catalog harvesting + purchase-history import/matching."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.models.catalog import Purchase
from headroom.schemas.admin import CatalogRefreshStarted, PurchaseImport, PurchaseRead
from headroom.services import catalog_service
from headroom.services.melin_recap import MelinRecapError

logger = logging.getLogger(__name__)

router = APIRouter()


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
async def import_purchases(data: PurchaseImport, db: AsyncSession = Depends(get_db)):
    """Store purchase line items (from order emails). Fields per item:
    item_title (required), order_ref, order_date (ISO), price, quantity, raw."""
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
async def rematch_purchases(db: AsyncSession = Depends(get_db)):
    """Re-run purchase→hat matching (e.g. after adding hats or colorways)."""
    return await catalog_service.match_purchases_to_hats(db)
