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


# The constructions melin ships often enough to be worth offering as choices.
#
# Deliberately a list and NOT a StrEnum, unlike style/size/condition above:
# those are closed sets this app defines, but construction is whatever melin
# decided to make this season. Specialty fabrics appear in collab and seasonal
# drops with no warning, and an enum would make each one unrecordable until
# somebody shipped a migration — the owner holding the hat and reading its tag
# would lose to a list written months earlier.
#
# So this is the structured half of a structured-plus-free-form field: the UI
# offers these, the Claude tool schema asks for these spellings, and anything
# else a person types is stored verbatim. `GET /api/meta/constructions` merges
# this list with the distinct values already in the database, so a fabric typed
# once becomes a suggestion from then on.
KNOWN_CONSTRUCTIONS: tuple[str, ...] = (
    "HYDRO",
    "HYDROLite",
    "Thermal",
    "Brushed Cotton",
    "Canvas",
    "Corduroy",
    "Linen",
    "Mesh Trucker",
    "Suede",
    "Wool Blend",
)


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


def construction_from_flags(hydrolite: bool | None, hydro: bool | None) -> str | None:
    """The construction text a pre-2.11 client meant by its boolean flags.

    Construction used to be two booleans. Clients built against that — the
    documented iOS Shortcut, anything a person automated — still send them, and
    silently dropping their input would be worse than the enum this replaced.

    Callers must only apply this when `construction` was absent, and must NOT
    assign the result when it is None: `hat_service` updates via
    `model_dump(exclude_unset=True)`, so touching the attribute at all marks it
    as set, and a PUT changing only the brand would blank the construction.
    """
    if hydrolite:
        return "HYDROLite"
    if hydro:
        return "HYDRO"
    return None


class HatCreate(BaseModel):
    case_id: int | None = None
    condition: HatCondition
    size: HatSize
    style: HatStyle
    # Free-form: "HYDRO", "HYDROLite", "Thermal", or whatever the tag says.
    construction: str | None = None
    date_last_worn: date | None = None
    # Both accepted at creation because the owner frequently knows them while
    # the analyser cannot: a collection name is printed on the box or the hang
    # tag, not visible in a photo of the hat. Withholding these until the Edit
    # form meant typing them twice, or hoping Claude guessed.
    artist_series: str | None = None
    model_name: str | None = None
    # Same reasoning, applied to cost basis: the receipt is in hand at the
    # moment a hat is added and nowhere to be found a week later. Without this
    # the only ways to record a price were the Edit form or an order-history
    # import, so anything bought secondhand or in person had no cost basis at
    # all — and a purchase price is the one figure in this app that is a fact
    # rather than an estimate.
    purchase_price: float | None = None
    purchased_at: datetime | None = None
    # Deprecated, accepted for back-compat. Read `construction` instead.
    hydrolite: bool = False
    hydro: bool = False

    @model_validator(mode="after")
    def _fold_legacy_flags(self) -> "HatCreate":
        if self.construction is None:
            legacy = construction_from_flags(self.hydrolite, self.hydro)
            if legacy is not None:
                self.construction = legacy
        return self


class HatUpdate(BaseModel):
    condition: HatCondition | None = None
    size: HatSize | None = None
    style: HatStyle | None = None
    construction: str | None = None
    date_last_worn: date | None = None
    # Deprecated, accepted for back-compat. Read `construction` instead.
    #
    # NOT folded into `construction` here, unlike `HatCreate`: doing that needs
    # the hat's current state, because a client sending only `hydrolite: false`
    # means "clear HYDROLite", not "clear whatever construction this hat has".
    # `hat_service.update_hat` resolves it where the hat is in hand.
    hydrolite: bool | None = None
    hydro: bool | None = None
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
    construction: str | None = None
    # Derived from `construction`; still sent because the UI badges and the
    # search filters both key off them.
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
    resale_price_scope: str | None = None
    analysis_status: str | None = None
    analysis_stage: str | None = None
    analysis_job_id: int | None = None
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
