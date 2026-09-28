import re
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from headroom.models.hat import ResaleScope
from headroom.schemas.case import CaseType
from headroom.schemas.common import (
    Brand,
    Colorway,
    Construction,
    Counterparty,
    LogoDetected,
    LongNotes,
    ModelName,
    Money,
    Series,
    ShortNotes,
    StyleDescriptor,
    clean_text,
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


#: How each size is printed — the option label and every list (served by
#: `GET /api/meta/sizes`). Beside the enum for the reason `STYLE_LABELS` is:
#: search matches on it too. The value is `x_large`, every page says
#: `X Large`, and a search for `x-large` or `xlarge` found nothing.
SIZE_LABELS: dict[str, str] = {
    "small": "Small",
    "classic": "Classic",
    "x_large": "X Large",
}


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


def condition_label(value: str) -> str:
    """How a condition is printed — "New With Tags". One rule for the option
    list (`GET /api/meta/conditions`) and the server-rendered report, which
    printed the value with its underscores swapped out ("new with tags")."""
    return value.replace("_", " ").title()


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
    the split `naming.token_set` makes (the tokenizer the matcher and the
    marketplace pricer share) for these ASCII names, so a construction found
    here is found by the matcher too."""
    return frozenset(_NON_WORD.sub(" ", (text or "").lower()).split())


#: Every word of every known construction, for token-bag arithmetic (strip the
#: construction words out of a model name, or test two bags for a contradiction).
CONSTRUCTION_TOKENS: frozenset[str] = frozenset(
    t for known in KNOWN_CONSTRUCTIONS for t in _construction_tokens(known)
)


def constructions_in(text: str | None) -> frozenset[str]:
    """The known constructions `text` names — each as its canonical spelling.

    Token-SUBSET, so `Wool Blend` needs both words and `HYDROLite` is its own
    token rather than a HYDRO with a suffix (a substring test reads every
    HYDROLite as a HYDRO too). Four modules used to answer this question with
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


class ColorTier(StrEnum):
    """How much of the hat a color covers. The vocabulary the Claude tool
    schema already enforces (`claude_analysis`), now enforced on the manual
    edit path too."""

    primary = "primary"
    secondary = "secondary"
    tertiary = "tertiary"
    accent = "accent"


class AnalysisStatus(StrEnum):
    """Where a hat's analysis stands. `pending` is the only non-terminal one."""

    pending = "pending"
    ok = "ok"
    fallback = "fallback"
    skipped = "skipped"
    error = "error"


class AnalysisStage(StrEnum):
    """The step a running analysis is on — `hat_analysis_pipeline.STAGE_*`,
    held to these values by `tests/test_wire_vocabulary.py`."""

    cutout = "cutout"
    identifying = "identifying"
    pricing = "pricing"
    resale = "resale"


class ColorTag(BaseModel):
    """A hat's color as it is READ back — lenient on purpose.

    Not the write body. It was both, which is how `PUT /colors` came to store a
    5,000-character name into a `String(50)`, `javascript:alert(1)` as a hex,
    `banana` as a tier and a bidi override in a name. `ColorTagWrite` below is
    the body; this stays tolerant because a row a hand-edited database holds
    must not 500 the whole hat list.
    """

    color_name: str
    general_color: str = ""
    hex_value: str
    dominance_rank: int
    tier: ColorTier = ColorTier.primary

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
    def _primary_when_null_or_unknown(cls, v: str | None) -> ColorTier:
        # Unknown degrades like NULL does, for the same reason: every write
        # path now refuses a tier outside the vocabulary, so only a row edited
        # by hand can carry one, and that must not take the hat list down.
        try:
            return ColorTier(v)
        except ValueError:
            return ColorTier.primary


#: The most colors one hat may carry. Claude returns at most five and the
#: mask extractor three; this leaves room for a person adding accents by hand
#: and refuses the 3,000-row body the unbounded list accepted.
MAX_COLORS_PER_HAT = 20

_HEX_RE = re.compile(r"^#[0-9a-f]{6}$")


def _canonical_hex(value: object) -> object:
    """`8CB9E1`, `#8cb9e1` and `#8cb` are the same color; store one spelling.

    Normalizes before the pattern check rather than instead of it: the case,
    the missing `#` and CSS's three-digit shorthand are spellings, anything
    else (`javascript:…`, `#12`) is not a color and is refused.
    """
    if not isinstance(value, str):
        return value
    v = value.strip().lower()
    if not v.startswith("#"):
        v = f"#{v}"
    if len(v) == 4:
        v = "#" + "".join(ch * 2 for ch in v[1:])
    return v


def _is_hex(value: str) -> str:
    if not _HEX_RE.match(value):
        raise ValueError("must be a #rrggbb color")
    return value


#: `#rrggbb`, lowercase — the only shape `hat_colors.hex_value` (String(7))
#: holds and the color-distance search can parse.
HexColor = Annotated[str, BeforeValidator(_canonical_hex), AfterValidator(_is_hex)]


class ColorTagWrite(BaseModel):
    """One color in a `PUT /api/hats/{id}/colors` body.

    Sized to `hat_colors` (`color_name` String(50), `general_color` String(30))
    and cleaned like every other name on the wire. No `dominance_rank`: the
    route ranks by position and always has, so a required field it then
    discarded was a promise the server did not keep — clients may still send
    it, and it is ignored.
    """

    #: Blank means "name it after the hex" — the palette name the swatch snaps
    #: to, which is a real name rather than a stand-in like "unnamed".
    color_name: clean_text(50) = None
    #: Blank means "derive it from the hex" (snapped to the palette).
    general_color: clean_text(30) = None
    hex_value: HexColor
    tier: ColorTier = ColorTier.primary


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


def _not_in_the_future(v: date) -> date:
    """"Last worn 2099-01-01" is a typo, not a plan.

    Tomorrow by UTC is allowed and nothing later: the furthest-ahead zone runs
    UTC+14, so UTC's date plus one is the latest calendar day it is anywhere,
    and a client ahead of the server's day is still telling the truth. UTC
    rather than `date.today()`, which reads the host's zone and so refused a
    real "tomorrow" on a dev machine west of Greenwich.
    """
    if v > datetime.now(timezone.utc).date() + timedelta(days=1):
        raise ValueError("cannot be in the future")
    return v


#: A calendar day a hat was worn. One definition for every door the date comes
#: through: the rule used to live on `WearCreate` alone, so `PUT /api/hats/{id}`
#: stored `2099-01-01` as the last-worn date — and because a wear only ever
#: moves that date FORWARD, no real wear could correct it afterwards.
WornDate = Annotated[date, AfterValidator(_not_in_the_future)]


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
    date_last_worn: WornDate | None = None
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
    # OMITTED means "leave it"; these four have no "cleared" state, so an
    # explicit `null` is refused below rather than reaching a NOT NULL column.
    limited_edition: bool | None = None
    condition: HatCondition | None = None
    size: HatSize | None = None
    style: HatStyle | None = None
    construction: Construction = None
    date_last_worn: WornDate | None = None
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

    @field_validator("limited_edition", "condition", "size", "style", mode="before")
    @classmethod
    def _omit_rather_than_null(cls, v: object) -> object:
        # `hat_service.update_hat` applies `model_dump(exclude_unset=True)`, so
        # an explicit null used to travel all the way to the commit and come
        # back as an IntegrityError — a 500 and an `error.unhandled` row for
        # what is a malformed request. The null-vs-omitted distinction is the
        # one `CaseUpdate.capacity` draws; these fields simply have no null.
        if v is None:
            raise ValueError("may be omitted but not null")
        return v


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


# ---- the price-provenance clumps, on the wire ------------------------------- #
#
# One base per `models.hat` mixin (`NewPriceColumns`, `ResaleColumns`,
# `EbayCompsColumns`, `DispositionColumns`), so each clump's names are declared
# once on each side of the ORM instead of restated field by field wherever they
# travel. `HatRead` inherits all four and `schemas.admin.EbayComps` IS the eBay
# one; the wire shape stays flat, so clients see the same keys.
# `tests/test_schema_consistency.py::test_each_price_clump_is_one_set_of_names_
# from_model_to_wire` holds each base to its mixin, name for name.


class NewPriceFields(BaseModel):
    estimated_new_price: float | None = None
    estimated_new_price_source: str | None = None


class ResaleFields(BaseModel):
    resale_price: float | None = None
    resale_price_source: str | None = None
    resale_price_url: str | None = None
    resale_checked_at: datetime | None = None
    resale_price_scope: ResaleScope | None = None


class EbayComps(BaseModel):
    """The price block `find_comps` writes onto a hat."""

    ebay_avg_price: float | None = None
    ebay_median_price: float | None = None
    ebay_listing_count: int | None = None
    ebay_search_url: str | None = None
    ebay_checked_at: datetime | None = None


class DispositionFields(BaseModel):
    disposed_at: datetime | None = None
    disposed_via: DisposedVia | None = None
    disposed_price: float | None = None
    disposed_to: str | None = None
    disposed_notes: str | None = None


# Populated straight off the ORM object via `HatRead.model_validate(hat)` —
# every field below is either a Hat column or one of the derived properties on
# the model, so there is no hand-written mapper to keep in step. Adding a hat
# column is the model, its static DDL in `database._HAT_COLUMN_DDL`, a field
# here (or in the clump base it belongs to) and its mirror in
# `frontend/src/types/index.ts`; `tests/test_schema_consistency.py`
# (`test_an_upgraded_database_has_every_model_column` and
# `test_each_price_clump_is_one_set_of_names_from_model_to_wire`) fails when
# the first two disagree or a clump loses a name. (Kept as a
# comment, not a docstring: docstrings surface in the public OpenAPI schema,
# and this is an internal note.)
class HatRead(NewPriceFields, ResaleFields, EbayComps, DispositionFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int | None
    position_in_case: int | None
    #: True when the hat sits in a room with no case.
    direct_room_id: int | None = None
    limited_edition: bool = False
    display_id: str | None
    case_display_id: str | None
    # The closed vocabularies below are published AS enums, so the OpenAPI
    # document states them and `tests/test_wire_vocabulary.py` can hold the
    # TypeScript unions that restate them to the same values. As bare `str`
    # they were four hand-typed copies nothing checked.
    case_type: CaseType | None
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
    # "owner" when a person set these colors — re-analysis then keeps them, and
    # the hat page can say so; null when analysis wrote them.
    colors_source: str | None = None
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
    # The new-price and resale clumps come from `NewPriceFields` and
    # `ResaleFields`; the disposition and eBay ones from their bases too.
    analysis_status: AnalysisStatus | None = None
    analysis_stage: AnalysisStage | None = None
    analysis_stage_at: datetime | None = None
    analysis_job_id: int | None = None
    analysis_error: str | None = None
    analyzed_at: datetime | None = None

    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _stage_only_while_running(self) -> "HatRead":
        """A stage is meaningless once the work it describes has finished.

        Derived here rather than cleared at each terminal transition: eight
        separate places set a terminal `analysis_status`, and any one of them
        forgetting would leave the UI reporting a step that stopped running —
        a stale spinner with a confident label, which is worse than no label.
        Doing it once, on the way out, makes that impossible.

        Two kinds of work run, not one. An analysis runs while the status is
        `pending`. A RE-CUT (`POST /recut`) deliberately leaves the analysis
        record alone — status included — and works from the retained original,
        so it is identified by what it does to the hat: the canonical photo is
        the uncut original until the new cutout lands. Keyed on the status
        alone, the page showed that original, background and all, with no
        sign anything was happening, and had no reason to poll.
        """
        recutting = (
            self.analysis_stage == AnalysisStage.cutout
            and self.original_path is not None
            and self.photo_path == self.original_path
        )
        if self.analysis_status != AnalysisStatus.pending and not recutting:
            self.analysis_stage = None
            self.analysis_stage_at = None
        return self


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
    """The whole palette, in the order it should be ranked. Replaces the set."""

    colors: list[ColorTagWrite] = Field(max_length=MAX_COLORS_PER_HAT)


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
    #: The wearer's calendar day. Clients should send it: "today" is a
    #: question about where the person is, and the server's answer — see
    #: `hat_service.owner_today` — is only a fallback for clients that don't.
    worn_at: WornDate | None = None
