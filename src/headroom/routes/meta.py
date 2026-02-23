from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.hat import HatCondition, HatSize, HatStyle
from headroom.services import room_service

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
    return [{"value": r.id, "label": r.name} for r in rooms]
