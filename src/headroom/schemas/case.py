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
    # Per-case hat capacity; None → type default (`capacity.MAX_REGULAR` /
    # `capacity.MAX_BEANIE`, not restated here). The
    # regular default carries one hat of overfill latitude; the beanie default
    # carries none, and neither does a number stated here — a stated capacity
    # is exact.
    capacity: int | None = Field(None, ge=1, le=50)


class CaseUpdate(BaseModel):
    case_type: CaseType | None = None
    room_id: int | None = None
    # `null` means "back to the type default"; OMITTED means "leave it". The
    # service tells the two apart with `model_fields_set` — before it did,
    # a per-case override could be set but never removed from the UI.
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
    # No `photo_path`: there is no case-photo feature (cases show a collage of
    # their hats). The column still exists on the model — dropping it is a
    # migration — but publishing a field no client reads is a promise about a
    # feature that does not exist.
    capacity: int | None
    hat_count: int
    # What the physical case cost new. Not a column: every case is the
    # same product at the same price, so a per-row copy would be 40
    # duplicates of one number waiting to disagree.
    retail_price: float
    beanie_count: int
    regular_count: int
    room_id: int
    room_name: str
    # Computed server-side from `services/capacity`, the same rule the write
    # path enforces. Sent so the case picker can gray out a case that would
    # 409 on save rather than letting you pick it and fail — at 40-60 cases
    # you cannot eyeball which are full or hold the wrong hat type.
    # Photo paths of the hats inside, newest-first-ish (id order), capped at
    # four. The Cases grid renders these as a collage: a photo of the case
    # itself is the same gray box for every case, where the hats are the thing
    # you are actually looking for.
    hat_thumbs: list[str] = []
    accepts_regular: bool = True
    accepts_beanie: bool = True
    #: Slots left before FULL — zero at nominal, even though one more will
    #: still be accepted. "3 of 3" has to read as full.
    free_regular: int = 0
    free_beanie: int = 0
    #: Past nominal: a fourth hat is in a three-hat case. Allowed, but the
    #: grids and the picker say so rather than presenting it as normal.
    overfull: bool = False
    #: Nominal capacity for this case, so the UI can render "3 of 3" without
    #: re-deriving the default it would then get wrong for an override.
    nominal_capacity: int
    #: Both type defaults, so no client has to restate them. The detail page
    #: hardcoded `capacity ?? 4` / `?? 6` — 4 being the OVERFILL limit rather
    #: than nominal, so a full three-hat case displayed "3/4". Served rather
    #: than restated because the beanie figure has now moved twice (3 → 8 → 6),
    #: and every hand-written copy was wrong for a while after each move.
    nominal_regular: int
    nominal_beanie: int
    created_at: datetime
    updated_at: datetime


class CaseDetail(CaseRead):
    hats: list[HatSummary]
