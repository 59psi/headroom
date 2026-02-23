from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel


class HatCondition(StrEnum):
    new_with_tags = "new_with_tags"
    new = "new"
    worn = "worn"


class HatSize(StrEnum):
    small = "small"
    standard = "standard"
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
    beanie = "beanie"


class ColorTag(BaseModel):
    color_name: str
    hex_value: str
    dominance_rank: int

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


class HatRead(BaseModel):
    id: int
    case_id: int | None
    position_in_case: int | None
    display_id: str | None
    case_display_id: str | None
    photo_path: str | None
    condition: HatCondition
    date_last_worn: date | None
    size: HatSize
    style: HatStyle
    is_beanie: bool
    colors: list[ColorTag]
    created_at: datetime
    updated_at: datetime


class ColorsUpdate(BaseModel):
    colors: list[ColorTag]


class HatAssign(BaseModel):
    case_id: int | None
