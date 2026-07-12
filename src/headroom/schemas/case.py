from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CaseType(StrEnum):
    archive = "archive"
    daily_wear = "daily_wear"


class CaseCreate(BaseModel):
    case_type: CaseType
    room_id: int = 1
    # Per-case hat capacity; None → type default (4 regular / 6 beanie)
    capacity: int | None = Field(None, ge=1, le=50)


class CaseUpdate(BaseModel):
    case_type: CaseType | None = None
    room_id: int | None = None
    capacity: int | None = Field(None, ge=1, le=50)


class HatSummary(BaseModel):
    id: int
    display_id: str | None
    style: str
    is_beanie: bool
    photo_path: str | None

    model_config = {"from_attributes": True}


class CaseRead(BaseModel):
    id: int
    case_type: CaseType
    sequence_number: int
    display_id: str
    photo_path: str | None
    capacity: int | None
    hat_count: int
    beanie_count: int
    regular_count: int
    room_id: int
    room_name: str
    created_at: datetime
    updated_at: datetime


class CaseDetail(CaseRead):
    hats: list[HatSummary]
