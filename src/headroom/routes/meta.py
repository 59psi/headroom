from fastapi import APIRouter

from headroom.schemas.hat import HatCondition, HatSize, HatStyle

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
