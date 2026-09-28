from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.routes._api import DomainErrorRoute
from headroom.schemas.search import (
    MAX_QUERY_LENGTH,
    ColorScope,
    ColorSearchResult,
    DuplicateGroupRead,
    SearchResult,
)
from headroom.services import duplicate_service, search_service

router = APIRouter(prefix="/api/search", tags=["search"], route_class=DomainErrorRoute)


@router.get("", response_model=list[SearchResult])
async def search(
    response: Response,
    q: str = Query(..., min_length=1, max_length=MAX_QUERY_LENGTH),
    exact_colors: bool = Query(False),
    room_id: int | None = Query(None),
    color_scope: ColorScope = Query(
        ColorScope.major,
        description=(
            "Which swatches a color term may match: 'major' (the hat's own"
            " colors, the default), 'accent' (logos, piping, underbrims), or"
            " 'all'."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """Every active hat matching all the terms, up to `SEARCH_LIMIT`.

    `X-Total-Count` is the uncapped number — the same header, for the same
    reason, as `GET /api/hats`: a list cut at the cap otherwise reads as the
    whole answer, and the newest matches are the ones it drops.
    """
    hats = await search_service.search_hats(
        db, q, exact_colors=exact_colors, room_id=room_id, color_scope=color_scope,
        limit=search_service.SEARCH_LIMIT,
    )
    response.headers["X-Total-Count"] = str(
        await search_service.count_search(
            db, q, exact_colors=exact_colors, room_id=room_id, color_scope=color_scope
        )
    )
    return [SearchResult.model_validate(h) for h in hats]


@router.get("/color", response_model=list[ColorSearchResult])
async def search_by_color(
    # Validated by the schema like every other parameter, so a bad value
    # answers the same 422 shape as `limit=0` beside it. The handler checked it
    # by hand and raised a 422 whose `detail` was a string where every other
    # 422 carries the list.
    hex: str = Query(
        ...,
        pattern=r"^#?[0-9A-Fa-f]{6}$",
        description="Target color, e.g. 8cb9e1 or #8cb9e1",
    ),
    room_id: int | None = Query(None),
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Hats ranked by perceptual closeness to a target color (nearest first)."""
    ranked = await search_service.search_hats_by_color(db, hex, room_id=room_id, limit=limit)
    return [
        ColorSearchResult.model_validate(
            {
                **SearchResult.model_validate(m.hat).model_dump(),
                "matched_hex": m.hex_value,
                "distance": m.distance,
                "matched_rank": m.rank,
            }
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
            hats=[SearchResult.model_validate(h) for h in g.hats],
        )
        for g in groups
    ]
