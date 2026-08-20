from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.models.hat import Hat
from headroom.schemas.hat import (
    KNOWN_CONSTRUCTIONS,
    HatCondition,
    HatSize,
    HatStyle,
)
from headroom.services import room_service, vocabulary
from headroom.services.catalog_service import catalog_options
from headroom.services.color_extraction import palette

router = APIRouter(prefix="/api/meta", tags=["meta"])

STYLE_LABELS: dict[str, str] = {
    "a_game": "A-Game",
    "odysea": "Odysea",
    "trenches": "Trenches",
    "coronado": "Coronado",
    "eagle": "Eagle",
    "compass": "Compass",
    "legend": "Legend",
    "caddy": "Caddy",
    "coast": "Coast",
    "shore": "The Shore",
    "collab": "Collab",
    "beanie": "Beanie",
}


@router.get("/styles")
async def list_styles():
    return [{"value": s.value, "label": STYLE_LABELS.get(s.value, s.value)} for s in HatStyle]


@router.get("/sizes")
async def list_sizes():
    return [{"value": s.value, "label": s.value.replace("_", " ").title()} for s in HatSize]


@router.get("/conditions")
async def list_conditions():
    return [{"value": c.value, "label": c.value.replace("_", " ").title()} for c in HatCondition]


@router.get("/rooms")
async def list_rooms(db: AsyncSession = Depends(get_db)):
    rooms = await room_service.list_rooms(db)
    return [{"value": r.id, "label": r.name} for r, _count in rooms]


@router.get("/colors")
async def list_colors():
    """The curated color palette — the UI renders these as filter chips."""
    return palette()


@router.get("/constructions")
async def list_constructions(db: AsyncSession = Depends(get_db)):
    """Suggestions for the construction field: the curated list, plus anything
    already in use.

    Merged rather than curated-only so a specialty fabric typed once becomes a
    one-tap choice from then on — that is what stops the free-form half of the
    field from filling up with five spellings of the same material. Curated
    entries come first because they are the common answers; the rest follow
    alphabetically. Case-insensitive de-dupe, keeping the curated casing.
    """
    curated = {c.casefold() for c in KNOWN_CONSTRUCTIONS}
    in_use = await vocabulary.distinct_values(db, Hat.construction)
    return list(KNOWN_CONSTRUCTIONS) + [
        v for v in in_use if v.casefold() not in curated
    ]


@router.get("/collections")
async def list_collections(db: AsyncSession = Depends(get_db)):
    """Collection / collaboration names already in use, for autocomplete.

    No curated list, unlike constructions: melin names these for the partner or
    the drop, so any list written today is wrong by the next release. What
    stops "Neon"/"NEON"/"neon" becoming three collections is this plus
    `vocabulary.canonicalize` on write, not a fixed vocabulary.
    """
    return await vocabulary.distinct_values(db, Hat.artist_series)


@router.get("/colorways")
async def list_colorways(
    q: str | None = None,
    model: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Autocomplete from the harvested catalog: model names, or colorways
    for a specific model when `model` is given."""
    return await catalog_options(db, q=q, model=model)
