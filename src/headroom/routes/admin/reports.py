"""Printable HTML output: inventory report + QR case labels."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.services import report_service
from headroom.services.label_service import render_case_labels

router = APIRouter()


@router.get("/inventory-report", response_class=HTMLResponse)
async def inventory_report(
    include_disposed: bool = False,
    include_photos: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Print-friendly HTML report. Use browser Print → Save as PDF."""
    html = await report_service.render_report(
        db, include_disposed=include_disposed, include_photos=include_photos
    )
    return HTMLResponse(html)


@router.get("/case-labels", response_class=HTMLResponse)
async def case_labels(request: Request, db: AsyncSession = Depends(get_db)):
    """Printable QR label sheet — one label per case."""
    base = str(request.base_url)
    return HTMLResponse(await render_case_labels(db, base))
