import re
from datetime import date, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from headroom.schemas.common import (
    Brand, Colorway, Construction, Counterparty, LogoDetected, LongNotes, ModelName, Money,
    Series, ShortNotes, StyleDescriptor,
)

_NON_WORD = re.compile(r"[^a-z0-9]+")


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
    # melin ships this as "The Shore". Deliberately NOT added to
    # `melin_recap.STYLE_TO_CATEGORY`: the marketplace has no `shore` category
    # (sellers file these under odysea/compass), so mapping it would sweep an
    # empty category AND break resale lookups. Left out, `fetch_resale_stats`
    # falls through to its `keywords=model_name` branch, which does find
    # "The Shore Islands Hydro".
    shore = "shore"
    # melin's cold-weather shape, e.g. "Aviator Scout Thermal" (order #1318309,
    # Dec 2024, $179). Seasonal — it drops in winter and vanishes, which is why
    # the resale marketplace has none and a catalog sweep will not find it.
    # Same reasoning as `shore` for staying out of STYLE_TO_CATEGORY.
    aviator = "aviator"
    collab = "collab"
    # Beanies. melin names its beanie shapes the way it names any other model
    # (Journey, Destination, All Day — see the "Beanie Shape Guide"), so they
    # belong here as styles rather than collapsing into one bucket that cannot
    # tell a $79 Journey from a promo giveaway.
    #
    # `beanie` stays as the unspecified shape: existing rows use it, and a hat
    # whose shape you haven't identified is a real state.
    beanie = "beanie"
    all_day = "all_day"
    journey = "journey"
    destination = "destination"


#: Every style that is physically a beanie.
#:
#: `Hat.is_beanie` is a real column — search filters query it and case capacity
#: depends on it (`capacity.MAX_BEANIE` vs `capacity.MAX_REGULAR` to a case,
#: figures that live there and nowhere else) — but it is DERIVED
#: from style. This set is the single definition of that derivation, for the
#: same reason `Hat.set_construction` is the only writer of hydro/hydrolite:
#: the two can silently disagree otherwise.
#:
#: Adding a beanie shape without adding it here produces a hat that packs
#: 3-to-a-case instead of 6, is invisible to the Beanies filter, and makes the
#: case picker offer cases the save will then reject with a 409.
BEANIE_STYLES: frozenset[str] = frozenset(
    {
        HatStyle.beanie.value,
        HatStyle.all_day.value,
        HatStyle.journey.value,
        HatStyle.destination.value,
    }
)


#: How each style is printed — the option label, every list, the report.
#: Beside the enum rather than in `routes/meta.py`, because search matches on
#: it too: the value is `a_game`, the page says `A-Game`, and a search for
#: what the page says used to find nothing.
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
    "aviator": "Aviator",
    "collab": "Collab",
    "beanie": "Beanie (unspecified)",
    "all_day": "All Day Beanie",
    "journey": "Journey Beanie",
    "destination": "Destination Beanie",
}


def is_beanie_style(style: str | None) -> bool:
    """Whether a style value denotes a beanie. The one place that decides."""
    return bool(style) and str(style) in BEANIE_STYLES


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
    "Denim",
    "Linen",
    "Mesh Trucker",
    "Suede",
    "Wool Blend",
)


def _construction_tokens(text: str | None) -> frozenset[str]:
    """Words of `text`, lowercased, punctuation and hyphens treated as spaces —
    the same bag `melin_recap.model_tokens` and `catalog_service._model_tokens`
    build, so a construction found here is found by the matcher too."""
    return frozenset(_NON_WORD.sub(" ", (text or "").lower()).split())


#: Every word of every known construction, for token-bag arithmetic (strip the
#: construction words out of a model name, or test two bags for a contradiction).
CONSTRUCTION_TOKENS: frozenset[str] = frozenset(
    t for known in KNOWN_CONSTRUCTIONS for t in _construction_tokens(known)
)


def constructions_in(text: str | None) -> frozenset[str]:
    """The known constructions `text` names — each as its canonical spelling.

    Token-SUBSET, so `Wool Blend` needs both words and `HYDROLite` is its own
    token rather than a HYDRO with a suffix (the substring confusion CLAUDE.md
    warns about repeatedly). Four modules used to answer this question with
    four tokenizations of their own; this is the one they share.
    """
    have = _construction_tokens(text)
    if not have:
        return frozenset()
    return frozenset(c for c in KNOWN_CONSTRUCTIONS if _construction_tokens(c) <= have)


def strip_constructions(text: str | None, *, keep: str | None = None) -> str | None:
    """Remove every known construction phrase from a display string.

    Word-boundary, case-insensitive, whitespace re-normalized; `keep` (the
    construction the owner stated) survives. Returns None when nothing is left
    — "Hydro" strips to nothing, and an empty name is worse than none. Used by
    the analysis pipeline (a name must not assert a construction nobody
    stated) and the construction audit (undo one that was written).
    """
    if not text:
        return text
    keep_key = (keep or "").casefold()
    cleaned = text
    for known in KNOWN_CONSTRUCTIONS:
        if keep_key and known.casefold() == keep_key:
            continue
        cleaned = re.sub(rf"\b{re.escape(known)}\b", " ", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()) or None


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
    # Put the hat straight in a room, with no case. Ignored when `case_id` is
    # given — a cased hat takes its case's room.
    room_id: int | None = None
    limited_edition: bool = False
    condition: HatCondition
    size: HatSize
    style: HatStyle
    # Free-form: "HYDRO", "HYDROLite", "Thermal", or whatever the tag says.
    construction: Construction = None
    date_last_worn: date | None = None
    # Both accepted at creation because the owner frequently knows them while
    # the analyzer cannot: a collection name is printed on the box or the hang
    # tag, not visible in a photo of the hat. Withholding these until the Edit
    # form meant typing them twice, or hoping Claude guessed.
    artist_series: Series = None
    model_name: ModelName = None
    # Same reasoning, applied to cost basis: the receipt is in hand at the
    # moment a hat is added and nowhere to be found a week later. Without this
    # the only ways to record a price were the Edit form or an order-history
    # import, so anything bought secondhand or in person had no cost basis at
    # all — and a purchase price is the one figure in this app that is a fact
    # rather than an estimate.
    purchase_price: Money | None = None
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
    limited_edition: bool | None = None
    condition: HatCondition | None = None
    size: HatSize | None = None
    style: HatStyle | None = None
    construction: Construction = None
    date_last_worn: date | None = None
    # Deprecated, accepted for back-compat. Read `construction` instead.
    #
    # NOT folded into `construction` here, unlike `HatCreate`: doing that needs
    # the hat's current state, because a client sending only `hydrolite: false`
    # means "clear HYDROLite", not "clear whatever construction this hat has".
    # `hat_service.update_hat` resolves it where the hat is in hand.
    hydrolite: bool | None = None
    hydro: bool | None = None
    brand: Brand = None
    logo_detected: LogoDetected = None
    artist_series: Series = None
    model_name: ModelName = None
    colorway: Colorway = None
    purchase_price: Money | None = None
    purchased_at: datetime | None = None
    style_descriptor: StyleDescriptor = None
    design_notes: LongNotes = None
    owner_notes: LongNotes = None
    estimated_new_price: Money | None = None
    resale_price: Money | None = None


# Populated straight off the ORM object via `HatRead.model_validate(hat)` —
# every field below is either a Hat column or one of the derived properties on
# the model, so there is no hand-written mapper to keep in step. Adding a column
# is still FOUR edits — the model, `database._HAT_COLUMN_DDL`, this class and
# `frontend/src/types/index.ts` — and skipping one is silent (CLAUDE.md, "Adding
# a Hat column"). (Kept as a comment, not a docstring: docstrings surface in the
# public OpenAPI schema, and this is an internal note.)
class HatRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int | None
    position_in_case: int | None
    #: True when the hat sits in a room with no case.
    direct_room_id: int | None = None
    limited_edition: bool = False
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
    # Yours. No analysis path ever writes it.
    owner_notes: str | None = None
    estimated_new_price: float | None = None
    estimated_new_price_source: str | None = None
    resale_price: float | None = None
    resale_price_source: str | None = None
    resale_price_url: str | None = None
    resale_checked_at: datetime | None = None
    resale_price_scope: str | None = None
    analysis_status: str | None = None
    analysis_stage: str | None = None
    analysis_stage_at: datetime | None = None
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
            self.analysis_stage_at = None
        return self


class DisposedVia(StrEnum):
    """How a hat left the collection — the one closed vocabulary on a hat that
    was a bare `str` validated by hand (a 400 where every other enum answers
    422 at the schema). Style, size and condition are all `StrEnum`s; this is
    the same shape for the same reason."""

    SOLD = "sold"
    GIFTED = "gifted"
    LOST = "lost"
    TRASHED = "trashed"
    TRADE = "trade"


class HatDispose(BaseModel):
    via: DisposedVia
    price: Money | None = None
    to: Counterparty = None
    notes: ShortNotes = None
    disposed_at: datetime | None = None

    @model_validator(mode="after")
    def _price_only_when_money_changed_hands(self):
        # A sale or a trade has a price; a gift, a loss or the bin does not.
        # The modal used to carry the previous sale's $50 into "lost", and the
        # server stored it — "disposed via lost for $50.00" in the audit log.
        if self.price is not None and self.via not in (DisposedVia.SOLD, DisposedVia.TRADE):
            raise ValueError(f"a price makes no sense for '{self.via.value}'")
        return self


class ColorsUpdate(BaseModel):
    colors: list[ColorTag]


class HatAssign(BaseModel):
    """Where a hat lives: a case, a room, or nowhere.

    The two are mutually exclusive by construction — `hat_service.assign_hat`
    clears one when it sets the other — because a cased hat's room is its
    case's room, and storing a second answer is storing something that can
    disagree.
    """

    case_id: int | None = None
    room_id: int | None = None


class WearCreate(BaseModel):
    worn_at: date | None = None  # default: today (UTC)

    @field_validator("worn_at")
    @classmethod
    def _not_in_the_future(cls, v: date | None) -> date | None:
        # "Last worn 2099-01-01" is a typo, not a plan. Tomorrow is allowed:
        # the client's calendar day can be ahead of the server's UTC one.
        if v is not None and v > date.today() + timedelta(days=1):
            raise ValueError("worn_at cannot be in the future")
        return v
