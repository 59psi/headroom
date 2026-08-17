from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CaseType(StrEnum):
    archive = "archive"
    daily_wear = "daily_wear"


class CaseCreate(BaseModel):
    case_type: CaseType
    # None → whichever room is currently flagged is_default, resolved in
    # case_service.create_case. Was a hardcoded 1, which pinned new cases to a
    # room that can now be deleted.
    room_id: int | None = None
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
    # The case-detail grid renders these as small tiles, so it wants the
    # thumbnail for the same reason the Hats gallery does.
    thumb_path: str | None = None

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
    # Computed server-side from `services/capacity`, the same rule the write
    # path enforces. Sent so the case picker can grey out a case that would
    # 409 on save rather than letting you pick it and fail — at 40-60 cases
    # you cannot eyeball which are full or hold the wrong hat type.
    accepts_regular: bool = True
    accepts_beanie: bool = True
    free_regular: int = 0
    free_beanie: int = 0
    created_at: datetime
    updated_at: datetime


class CaseDetail(CaseRead):
    hats: list[HatSummary]
