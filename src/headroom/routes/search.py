from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.hat import ColorTag
from headroom.schemas.search import SearchResult
from headroom.services.search_service import search_hats

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=list[SearchResult])
async def search(q: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db)):
    hats = await search_hats(db, q)
    return [
        SearchResult(
            id=h.id,
            display_id=h.display_id,
            case_display_id=h.case.display_id if h.case else None,
            photo_path=h.photo_path,
            style=h.style,
            condition=h.condition,
            size=h.size,
            is_beanie=h.is_beanie,
            colors=[
                ColorTag(
                    color_name=c.color_name,
                    hex_value=c.hex_value,
                    dominance_rank=c.dominance_rank,
                )
                for c in (h.colors or [])
            ],
        )
        for h in hats
    ]
