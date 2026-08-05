"""Colorway catalog harvesting + purchase-history import/matching."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.models.catalog import Purchase
from headroom.schemas.admin import PurchaseImport
from headroom.services import catalog_service
from headroom.services.melin_recap import MelinRecapError

router = APIRouter()


@router.post("/colorways/refresh")
async def refresh_colorway_catalog(db: AsyncSession = Depends(get_db)):
    """Harvest melinrecap listing titles into the colorway catalog."""
    try:
        return await catalog_service.harvest_catalog(db)
    except MelinRecapError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/purchases/import")
async def import_purchases(data: PurchaseImport, db: AsyncSession = Depends(get_db)):
    """Store purchase line items (from order emails). Fields per item:
    item_title (required), order_ref, order_date (ISO), price, quantity, raw."""
    result = await catalog_service.import_purchases(db, data.items)
    match = await catalog_service.match_purchases_to_hats(db)
    return {**result, **match}


@router.get("/purchases")
async def list_purchases(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(Purchase).order_by(Purchase.order_date.desc()))
    ).scalars().all()
    return [
        {
            "id": p.id, "order_ref": p.order_ref, "order_date": p.order_date,
            "item_title": p.item_title, "model_name": p.model_name,
            "colorway": p.colorway, "price": p.price, "quantity": p.quantity,
            "hat_id": p.hat_id, "source": p.source,
        }
        for p in rows
    ]


@router.post("/purchases/match")
async def rematch_purchases(db: AsyncSession = Depends(get_db)):
    """Re-run purchase→hat matching (e.g. after adding hats or colorways)."""
    return await catalog_service.match_purchases_to_hats(db)
