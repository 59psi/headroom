"""Printable HTML output: inventory report + QR case labels."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.services import export_service, report_service
from headroom.services.activity_service import log_activity
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


@router.get("/collection-export")
async def collection_export(
    title: str = "The Collection",
    include_values: bool = False,
    include_disposed: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """The collection as a downloadable zip — `index.html` plus an images folder.

    For showing someone the collection when they cannot reach the app. Share
    links are better when they can: those stay current and can be revoked,
    whereas this is a snapshot the moment it is downloaded.

    Values are OFF by default. This is the version you send a friend; the
    inventory report is the one with the money in it.
    """
    blob, filename = await export_service.build_export(
        db,
        title=title,
        include_values=include_values,
        include_disposed=include_disposed,
    )
    await log_activity(
        db, kind="collection.exported", entity_type="collection", entity_id=None,
        summary=f"Collection exported ({len(blob):,} bytes)",
        details={"include_values": include_values, "include_disposed": include_disposed},
    )
    await db.commit()  # log_activity is fire-and-forget; the caller commits
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/case-labels", response_class=HTMLResponse)
async def case_labels(request: Request, db: AsyncSession = Depends(get_db)):
    """Printable QR label sheet — one label per case."""
    base = str(request.base_url)
    return HTMLResponse(await render_case_labels(db, base))
