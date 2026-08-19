from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.hat import ColorTag
from headroom.schemas.search import DuplicateGroupRead, ColorSearchResult, SearchResult
from headroom.services.color_extraction import parse_hex
from headroom.services import duplicate_service
from headroom.services.search_service import search_hats, search_hats_by_color

router = APIRouter(prefix="/api/search", tags=["search"])


def _result_fields(h) -> dict:
    return {
        "id": h.id,
        "display_id": h.display_id,
        "case_display_id": h.case_display_id,
        "photo_path": h.photo_path,
        # The grid renders thumbnails; without this every result loaded the
        # full-size transparent PNG.
        "thumb_path": h.thumb_path,
        "style": h.style,
        "condition": h.condition,
        "size": h.size,
        "is_beanie": h.is_beanie,
        "brand": h.brand,
        "model_name": h.model_name,
        "colors": [
            ColorTag(
                color_name=c.color_name,
                general_color=c.general_color or "",
                hex_value=c.hex_value,
                dominance_rank=c.dominance_rank,
                tier=c.tier or "primary",
            )
            for c in (h.colors or [])
        ],
        "room_id": h.room_id,
        "room_name": h.room_name,
    }


@router.get("", response_model=list[SearchResult])
async def search(
    q: str = Query(..., min_length=1),
    exact_colors: bool = Query(False),
    room_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    hats = await search_hats(db, q, exact_colors=exact_colors, room_id=room_id)
    return [SearchResult(**_result_fields(h)) for h in hats]


@router.get("/color", response_model=list[ColorSearchResult])
async def search_by_color(
    hex: str = Query(..., description="Target color, e.g. 8cb9e1 or #8cb9e1"),
    room_id: int | None = Query(None),
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Hats ranked by perceptual closeness to a target color (nearest first)."""
    if parse_hex(hex) is None:
        raise HTTPException(status_code=422, detail="hex must be a 6-digit hex color")
    ranked = await search_hats_by_color(db, hex, room_id=room_id, limit=limit)
    return [
        ColorSearchResult(
            **_result_fields(m.hat),
            matched_hex=m.hex_value,
            distance=m.distance,
            matched_rank=m.rank,
        )
        for m in ranked
    ]


@router.get("/duplicates", response_model=list[DuplicateGroupRead])
async def find_duplicate_hats(db: AsyncSession = Depends(get_db)):
    """Hats that look like the same hat entered twice — usually from a bulk import.

    Reports only. Nothing is deleted or merged: owning the same cap twice, one
    kept new in the box, is a perfectly normal thing and only the owner knows
    which case this is.
    """
    groups = await duplicate_service.find_duplicates(db)
    return [
        DuplicateGroupRead(
            key=g.key,
            confidence=g.confidence,
            label=g.label,
            hats=[SearchResult(**_result_fields(h)) for h in g.hats],
        )
        for g in groups
    ]
