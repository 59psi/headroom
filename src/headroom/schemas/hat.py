from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel


class HatCondition(StrEnum):
    new_with_tags = "new_with_tags"
    new = "new"
    worn = "worn"


class HatSize(StrEnum):
    small = "small"
    classic = "classic"
    x_large = "x_large"


class HatStyle(StrEnum):
    a_game = "a_game"
    odysea = "odysea"
    trenches = "trenches"
    coronado = "coronado"
    eagle = "eagle"
    compass = "compass"
    legend = "legend"
    caddy = "caddy"
    coast = "coast"
    collab = "collab"
    beanie = "beanie"


class ColorTag(BaseModel):
    color_name: str
    general_color: str = ""
    hex_value: str
    dominance_rank: int
    tier: str = "primary"

    model_config = {"from_attributes": True}


class HatCreate(BaseModel):
    case_id: int | None = None
    condition: HatCondition
    size: HatSize
    style: HatStyle
    date_last_worn: date | None = None


class HatUpdate(BaseModel):
    condition: HatCondition | None = None
    size: HatSize | None = None
    style: HatStyle | None = None
    date_last_worn: date | None = None
    brand: str | None = None
    model_name: str | None = None
    style_descriptor: str | None = None
    design_notes: str | None = None
    estimated_new_price: float | None = None
    resale_price: float | None = None


class HatRead(BaseModel):
    id: int
    case_id: int | None
    position_in_case: int | None
    display_id: str | None
    case_display_id: str | None
    case_type: str | None
    photo_path: str | None
    condition: HatCondition
    date_last_worn: date | None
    size: HatSize
    style: HatStyle
    is_beanie: bool
    colors: list[ColorTag]
    room_id: int | None
    room_name: str | None

    # AI / pricing fields
    brand: str | None = None
    model_name: str | None = None
    model_confidence: str | None = None
    style_descriptor: str | None = None
    design_notes: str | None = None
    estimated_new_price: float | None = None
    estimated_new_price_source: str | None = None
    resale_price: float | None = None
    resale_price_source: str | None = None
    resale_price_url: str | None = None
    resale_checked_at: datetime | None = None
    analysis_status: str | None = None
    analysis_error: str | None = None
    analyzed_at: datetime | None = None

    created_at: datetime
    updated_at: datetime


class ColorsUpdate(BaseModel):
    colors: list[ColorTag]


class HatAssign(BaseModel):
    case_id: int | None
