from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


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


# What a hat gets when the caller doesn't say. Three entry points create hats
# without full details — the bulk-import form, its worker fallback, and the
# Android share target — and each used to restate these literals, so changing
# the default meant finding all three and they could silently disagree
# (photos shared from the phone landing differently than the same photos
# bulk-imported). One dict, imported by all of them.
HAT_DEFAULTS: dict[str, str] = {
    "condition": HatCondition.new.value,
    "size": HatSize.classic.value,
    "style": HatStyle.a_game.value,
}


class ColorTag(BaseModel):
    color_name: str
    general_color: str = ""
    hex_value: str
    dominance_rank: int
    tier: str = "primary"

    model_config = ConfigDict(from_attributes=True)

    # `general_color` and `tier` were added to hat_colors by migration. The DDL
    # carries a DEFAULT so rows should be backfilled, but a NULL read back from
    # a hand-edited or partially-migrated DB must degrade to the default rather
    # than 500 the whole hat list.
    @field_validator("general_color", mode="before")
    @classmethod
    def _blank_when_null(cls, v: str | None) -> str:
        return v or ""

    @field_validator("tier", mode="before")
    @classmethod
    def _primary_when_null(cls, v: str | None) -> str:
        return v or "primary"


class HatCreate(BaseModel):
    case_id: int | None = None
    condition: HatCondition
    size: HatSize
    style: HatStyle
    hydrolite: bool = False
    hydro: bool = False
    date_last_worn: date | None = None


class HatUpdate(BaseModel):
    condition: HatCondition | None = None
    size: HatSize | None = None
    style: HatStyle | None = None
    hydrolite: bool | None = None
    hydro: bool | None = None
    date_last_worn: date | None = None
    brand: str | None = None
    logo_detected: str | None = None
    artist_series: str | None = None
    model_name: str | None = None
    colorway: str | None = None
    purchase_price: float | None = None
    purchased_at: datetime | None = None
    style_descriptor: str | None = None
    design_notes: str | None = None
    estimated_new_price: float | None = None
    resale_price: float | None = None


# Populated straight off the ORM object via `HatRead.model_validate(hat)` —
# every field below is either a Hat column or one of the derived properties on
# the model, so adding a column means editing the model and this class, and
# nothing else. (Kept as a comment, not a docstring: docstrings surface in the
# public OpenAPI schema, and this is an internal note.)
class HatRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int | None
    position_in_case: int | None
    display_id: str | None
    case_display_id: str | None
    case_type: str | None
    photo_path: str | None
    original_path: str | None = None
    thumb_path: str | None = None
    condition: HatCondition
    date_last_worn: date | None
    wear_count: int
    size: HatSize
    style: HatStyle
    hydrolite: bool = False
    hydro: bool = False
    is_beanie: bool
    colors: list[ColorTag]
    room_id: int | None
    room_name: str | None

    # AI / pricing fields
    brand: str | None = None
    logo_detected: str | None = None
    artist_series: str | None = None
    model_name: str | None = None
    colorway: str | None = None
    purchase_price: float | None = None
    purchased_at: datetime | None = None
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
    analysis_stage: str | None = None
    analysis_error: str | None = None
    analyzed_at: datetime | None = None

    # v0.3 — disposition
    disposed_at: datetime | None = None
    disposed_via: str | None = None
    disposed_price: float | None = None
    disposed_to: str | None = None
    disposed_notes: str | None = None

    # v0.4 — eBay comps
    ebay_avg_price: float | None = None
    ebay_median_price: float | None = None
    ebay_listing_count: int | None = None
    ebay_search_url: str | None = None
    ebay_checked_at: datetime | None = None

    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _stage_only_while_pending(self) -> "HatRead":
        """A stage is meaningless once the analysis has finished.

        Derived here rather than cleared at each terminal transition: eight
        separate places set a terminal `analysis_status`, and any one of them
        forgetting would leave the UI reporting a step that stopped running —
        a stale spinner with a confident label, which is worse than no label.
        Doing it once, on the way out, makes that impossible.
        """
        if self.analysis_status != "pending":
            self.analysis_stage = None
        return self


class HatDispose(BaseModel):
    via: str  # sold | gifted | lost | trashed | trade
    price: float | None = None
    to: str | None = None
    notes: str | None = None
    disposed_at: datetime | None = None


class ColorsUpdate(BaseModel):
    colors: list[ColorTag]


class HatAssign(BaseModel):
    case_id: int | None


class WearCreate(BaseModel):
    worn_at: date | None = None  # default: today (UTC)
