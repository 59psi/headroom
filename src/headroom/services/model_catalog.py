"""The Claude models this build knows about, and what Anthropic lists live.

ONE table (`CATALOG`) answers every question the app asks about a model id:
what to call it, whether it is still the one to pick, what replaces it, and —
the question that actually breaks analyses — whether it accepts a forced
`tool_choice`. `claude_analysis` derives its forced-tool allow-list from here,
so the picker and the request builder can no longer disagree about a model.
They did: Fable 5.1 sat on the Settings roster as "most capable" while every
analysis sent it the forced tool choice it answers with a 400.

The table is curated, not fetched, because the Models API says nothing about
what matters to this app: which model is the sensible default, which one
cannot cache this app's prompt, which refuses a forced tool choice, what a
retired id should move to. What the API DOES know — which ids this key can
use today, and models newer than this build — comes from `list_live_models`
and is merged in by `merged_options`, cached for six hours per key.

Facts below were checked on 2026-09-28 against Anthropic's Models overview,
the Models API listing for a real key, and analyses of real hat photos.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Literal

from anthropic import APIConnectionError, APIStatusError, AuthenticationError

from headroom.config import settings as config_settings
from headroom.services import locks

logger = logging.getLogger(__name__)

Status = Literal["current", "legacy", "retired"]
Speed = Literal["Fastest", "Fast", "Moderate", "Slower"]


@dataclass(frozen=True)
class CatalogModel:
    """One model, under its canonical id plus every other id that names it.

    `aliases` are the OTHER spellings of the same model — a dated snapshot id
    (`claude-haiku-4-5-20251001`), or the old `-0` alias beside a dated id.
    The Models API lists the dated form for some models and the bare alias
    for others, and an install may have saved either; all of them resolve to
    this one entry, so the picker never shows one model twice.
    """

    id: str
    name: str
    status: Status
    #: Anthropic's own comparative-latency word; None where it was not given.
    speed: Speed | None
    #: Relative price per token, by the family's current price: Haiku 1,
    #: Sonnet 2, Opus 3, Fable 5. Not a dollar figure on purpose — a price
    #: list rots, and "5" still reads right when every number moves together.
    #: 4 is the gap between Opus and Fable, which costs 2.5x Opus 5.5.
    cost_level: int | None
    #: One short phrase for the option label, which the picker renders as
    #: "<name> — <summary>" and, on the default, appends " (default)" to —
    #: so it never names the default itself: an install whose
    #: HEADROOM_ANTHROPIC_MODEL points elsewhere would be told two models
    #: are the default. Short, because the select's closed face ellipsizes
    #: at phone width; the `note` carries the detail. None where the status
    #: is the whole story: the picker files legacy models under "Previous
    #: generation" and labels a retired one "(retired)", and a summary that
    #: repeats that reads "Opus 5 — Previous generation" nine times over.
    summary: str | None
    #: One sentence of detail for whoever is choosing.
    note: str | None
    #: The current model a legacy or retired one should move to.
    successor: str | None
    #: Accepts `tool_choice: {"type": "tool"}`. False for the models that
    #: answer it with a 400 — and for any model where it was never verified,
    #: because `auto` is accepted everywhere and costs only the guarantee.
    forced_tool: bool
    aliases: tuple[str, ...] = ()
    #: ISO date Anthropic says it will not retire the model before.
    retires_after: str | None = None

    @property
    def ids(self) -> tuple[str, ...]:
        return (self.id, *self.aliases)


def _legacy(id_: str, name: str, successor: str, cost_level: int, note: str, *,
            aliases: tuple[str, ...] = ()) -> CatalogModel:
    """A previous-generation model Anthropic still serves.

    Every one of these accepts a forced tool choice — that was verified per
    model when each was current, which is why they were on the old list.
    Speed is left unstated: Anthropic's latency words were given for the
    current lineup only, and a guess here would outrank a measurement.
    """
    return CatalogModel(
        id=id_, name=name, status="legacy", speed=None, cost_level=cost_level,
        summary=None, note=note, successor=successor,
        forced_tool=True, aliases=aliases,
    )


def _retired(id_: str, name: str, successor: str, *, forced_tool: bool,
             aliases: tuple[str, ...] = (), note: str | None = None) -> CatalogModel:
    """A model Anthropic no longer serves (404 `not_found_error`).

    Kept so an install that saved one sees WHY every analysis fails and what
    to move to, rather than an unexplained id under "Other".
    """
    return CatalogModel(
        id=id_, name=name, status="retired", speed=None, cost_level=None,
        summary=None,
        note=note or "Every analysis with this model fails; switch to its successor.",
        successor=successor, forced_tool=forced_tool, aliases=aliases,
    )


SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"
FABLE = "claude-fable-5-1"
HAIKU = "claude-haiku-4-5"

#: Order is the order the picker lists them in: the default first, then up
#: the capability ladder, then the one on its way out; then the previous
#: generation newest first; then what is gone.
CATALOG: tuple[CatalogModel, ...] = (
    # ---- current ------------------------------------------------------ #
    # The three newest refuse a forced tool choice, so their analyses take
    # the `auto` path — the system prompt and the user turn both instruct the
    # call, and Sonnet 5.5 returned a structured answer on 6 of 6 real photos
    # that way (Opus 5.5 likewise).
    CatalogModel(
        id=SONNET, name="Claude Sonnet 5.5", status="current", speed="Fast",
        cost_level=2, summary="fast and inexpensive",
        note=(
            "About 5 seconds per hat on real photos, with a structured answer"
            " every time; it thinks only when a photo calls for it."
        ),
        successor=None, forced_tool=False,
    ),
    CatalogModel(
        id=OPUS, name="Claude Opus 5.5", status="current", speed="Moderate",
        cost_level=3, summary="finer model names, slower",
        note=(
            "Names the exact line more often (\"Trenches Icon\" where Sonnet says"
            " \"Trenches\"), at about 11 seconds and about 1.7 times Sonnet 5.5's"
            " output per hat; it always thinks first."
        ),
        successor=None, forced_tool=False,
    ),
    CatalogModel(
        id=FABLE, name="Claude Fable 5.1", status="current", speed="Slower",
        cost_level=5, summary="most capable, priciest",
        note="Always thinks before answering, at five times Sonnet 5.5's price per token.",
        successor=None, forced_tool=False,
    ),
    CatalogModel(
        id=HAIKU, name="Claude Haiku 4.5", status="current", speed="Fastest",
        # "Per token", and the caveat in the label itself: per HAT it is not
        # reliably the cheapest, since its cache minimum is longer than this
        # app's prompt and it pays full input price for all of it every time
        # (measured: cache_write=0).
        cost_level=1, summary="cheapest per token, no caching",
        note=(
            "Its cache minimum is longer than this app's prompt, so every hat pays"
            " full input price, and it measured no faster than Sonnet 5.5 here."
        ),
        successor=None, forced_tool=True,
        # The old picker saved the dated id; both name the same model.
        aliases=("claude-haiku-4-5-20251001",),
        retires_after="2026-10-15",
    ),
    # ---- previous generation, still served ---------------------------- #
    _legacy("claude-fable-5", "Claude Fable 5", FABLE, 5,
            "Superseded by Fable 5.1 at the same price."),
    _legacy("claude-opus-5", "Claude Opus 5", OPUS, 3,
            "Superseded by Opus 5.5, which costs less per token."),
    _legacy("claude-sonnet-5", "Claude Sonnet 5", SONNET, 2,
            "Superseded by Sonnet 5.5 at the same price, which answered faster here."),
    _legacy("claude-opus-4-8", "Claude Opus 4.8", OPUS, 3,
            "Superseded by Opus 5.5."),
    _legacy("claude-opus-4-7", "Claude Opus 4.7", OPUS, 3,
            "Superseded by Opus 5.5."),
    _legacy("claude-opus-4-6", "Claude Opus 4.6", OPUS, 3,
            "Can't cache this app's prompt, so every hat pays full input price."),
    _legacy("claude-sonnet-4-6", "Claude Sonnet 4.6", SONNET, 2,
            "Costs more per token than Sonnet 5.5."),
    _legacy("claude-opus-4-5", "Claude Opus 4.5", OPUS, 3,
            "Superseded by Opus 5.5.", aliases=("claude-opus-4-5-20251101",)),
    _legacy("claude-sonnet-4-5", "Claude Sonnet 4.5", SONNET, 2,
            "Superseded by Sonnet 5.5.", aliases=("claude-sonnet-4-5-20250929",)),
    # ---- retired ------------------------------------------------------ #
    # The 4.x retirees were on the forced-tool list when they were served,
    # and stay marked so: the flag records what the model accepted. The 3.x
    # ones were never verified here, so they are not — moot either way, as
    # Anthropic answers 404 before it reads the tool choice.
    _retired("claude-opus-4-1", "Claude Opus 4.1", OPUS, forced_tool=True,
             note="Retired on 2026-08-05; every analysis with it now fails."),
    _retired("claude-opus-4-0", "Claude Opus 4", OPUS, forced_tool=True,
             aliases=("claude-opus-4-20250514",)),
    _retired("claude-sonnet-4-0", "Claude Sonnet 4", SONNET, forced_tool=True,
             aliases=("claude-sonnet-4-20250514",)),
    _retired("claude-3-7-sonnet-20250219", "Claude Sonnet 3.7", SONNET, forced_tool=False),
    _retired("claude-3-5-sonnet-20241022", "Claude Sonnet 3.5 (October 2024)", SONNET,
             forced_tool=False),
    _retired("claude-3-5-sonnet-20240620", "Claude Sonnet 3.5 (June 2024)", SONNET,
             forced_tool=False),
    _retired("claude-3-5-haiku-20241022", "Claude Haiku 3.5", HAIKU, forced_tool=False),
    _retired("claude-3-opus-20240229", "Claude Opus 3", OPUS, forced_tool=False),
    _retired("claude-3-haiku-20240307", "Claude Haiku 3", HAIKU, forced_tool=False),
)

_BY_ID: dict[str, CatalogModel] = {mid: m for m in CATALOG for mid in m.ids}


def forced_tool_ids() -> frozenset[str]:
    """Every id — canonical and alias — of a model that accepts a forced tool choice.

    `claude_analysis._FORCED_TOOL_CHOICE_MODELS` IS this set. It used to be a
    second, hand-kept list beside the picker's, and the two drifted.
    """
    return frozenset(mid for m in CATALOG if m.forced_tool for mid in m.ids)


def _undated(model_id: str) -> str | None:
    """`model_id` without an 8-digit date suffix, or None if it has none.

    The suffix must be a DATE, exactly as in
    `claude_analysis._accepts_forced_tool_choice`: `claude-opus-5-5` is
    `claude-opus-5` plus "-5", and treating any suffix as a snapshot would
    fold Opus 5.5 into Opus 5.
    """
    base, _, suffix = model_id.rpartition("-")
    return base if base and len(suffix) == 8 and suffix.isdigit() else None


def lookup(model_id: str) -> CatalogModel | None:
    """The catalog entry `model_id` names — canonically, as an alias, or dated."""
    entry = _BY_ID.get(model_id)
    if entry is None and (base := _undated(model_id)) is not None:
        entry = _BY_ID.get(base)
    return entry


# ------------------------------ live list ------------------------------ #


@dataclass(frozen=True)
class LiveModel:
    """One row of Anthropic's Models API, reduced to what the picker needs."""

    id: str
    display_name: str
    created_at: datetime | None
    #: Explicitly reported as accepting image input. A model that does not —
    #: or whose capabilities were not reported — cannot analyze a photo.
    image_input: bool


@dataclass(frozen=True)
class LiveListing:
    """What the Models API said for one key, or why it said nothing."""

    #: None when there is no live list (no key, or the call failed).
    models: tuple[LiveModel, ...] | None
    checked_at: datetime | None = None
    error: str | None = None


class ModelListingError(Exception):
    """The Models API could not be read. The message is short and safe to show."""


NO_KEY = "No Claude API key configured"

#: How long a live list stands before it is fetched again. Anthropic adds a
#: model every few months; the Settings page is opened far more often.
LIVE_TTL_S = 6 * 60 * 60
#: How long a FAILED fetch stands. Short, because the usual causes (no
#: network, an account out of credit) clear on their own, but not zero: every
#: Settings render would otherwise wait out the failure again. `?refresh=1`
#: skips it for whoever has just fixed the cause.
FAILURE_TTL_S = 5 * 60
#: The listing is a render-time call from the Settings page, so it gets a
#: short timeout and one retry, not the SDK's default two with backoff.
LIST_TIMEOUT_S = 10.0


def _image_input(capabilities: object) -> bool:
    """`capabilities.image_input.supported`, read through `model_dump()`.

    The SDK hands back a pydantic model here, not a dict — subscripting it or
    calling `.get` on it raises — and the field itself is optional.
    """
    if capabilities is None:
        return False
    dumped = capabilities.model_dump() if hasattr(capabilities, "model_dump") else capabilities
    if not isinstance(dumped, dict):
        return False
    image = dumped.get("image_input")
    return isinstance(image, dict) and image.get("supported") is True


async def list_live_models(api_key: str) -> list[LiveModel]:
    """Every model Anthropic lists for `api_key`.

    Every SDK failure comes out as `ModelListingError` with a short message;
    anything else is a bug, and `_fetch` catches that too. THE network seam:
    tests patch this attribute, and conftest makes it raise by default. The
    SDK paginates by itself under `async for`; the client is built by
    `claude_analysis._anthropic_client`, the same seam the analysis uses, so
    the suite's in-memory transport covers this call too.
    """
    # A real cycle: `claude_analysis` builds its forced-tool allow-list from
    # this module at import time, so importing it at the top here would hand
    # whichever loads second a half-initialized module.
    from headroom.services import claude_analysis  # noqa: PLC0415 — import cycle (see above)

    found: list[LiveModel] = []
    try:
        async with claude_analysis._anthropic_client(
            api_key, LIST_TIMEOUT_S, max_retries=1
        ) as client:
            async for info in client.models.list(limit=100):
                found.append(LiveModel(
                    id=info.id,
                    display_name=info.display_name or info.id,
                    created_at=info.created_at,
                    image_input=_image_input(info.capabilities),
                ))
    # Short sentences for a status line, never the SDK's full text: that can
    # run to a paragraph of JSON, and none of it is actionable on this page.
    except AuthenticationError as exc:
        raise ModelListingError("Anthropic rejected the API key") from exc
    except APIStatusError as exc:
        raise ModelListingError(f"Anthropic answered {exc.status_code}") from exc
    except APIConnectionError as exc:
        raise ModelListingError("Could not reach Anthropic") from exc
    return found


def _fingerprint(api_key: str) -> str:
    """What the cache is keyed by — never the key itself."""
    return hashlib.sha256(api_key.encode()).hexdigest()


@dataclass
class _Cached:
    fingerprint: str
    listing: LiveListing
    #: `time.monotonic()` when stored — immune to the wall clock moving.
    stored_at: float = field(default_factory=time.monotonic)

    def fresh_for(self, fingerprint: str) -> bool:
        ttl = LIVE_TTL_S if self.listing.models is not None else FAILURE_TTL_S
        return self.fingerprint == fingerprint and time.monotonic() - self.stored_at < ttl


#: ONE slot, not a dict per key: an install has one key at a time, and a
#: replaced key's list is garbage the moment it is replaced — so the cache
#: stays one entry however often the key changes.
_cache: _Cached | None = None


def clear_cache() -> None:
    global _cache
    _cache = None


async def _fetch(api_key: str) -> LiveListing:
    """One live read, as a listing. Never raises."""
    try:
        models = await list_live_models(api_key)
    except ModelListingError as exc:
        logger.warning("Claude model listing failed: %s (%r)", exc, exc.__cause__)
        return LiveListing(models=None, error=str(exc))
    # Broad on purpose: the picker must render on the catalog alone whatever
    # broke, and the traceback still reaches the log.
    except Exception:
        logger.exception("Claude model listing failed unexpectedly")
        return LiveListing(models=None, error="Unexpected error listing models")
    return LiveListing(models=tuple(models), checked_at=datetime.now(timezone.utc))


async def get_live_listing(api_key: str | None, *, refresh: bool = False) -> LiveListing:
    """The live list for `api_key`, from the cache when it is fresh. Never raises."""
    global _cache
    if not api_key:
        return LiveListing(models=None, error=NO_KEY)
    fp = _fingerprint(api_key)
    if not refresh and _cache is not None and _cache.fresh_for(fp):
        return _cache.listing
    # Serialized so two tabs opening Settings at once make one call. The
    # second waiter finds the first one's answer and stops — unless it asked
    # for a refresh, which is a request for a NEW answer.
    async with locks.loop_lock("claude-model-listing"):
        if not refresh and _cache is not None and _cache.fresh_for(fp):
            return _cache.listing
        listing = await _fetch(api_key)
        _cache = _Cached(fingerprint=fp, listing=listing)
        return listing


# ------------------------------ merging -------------------------------- #


@dataclass(frozen=True)
class ModelOption:
    """One picker entry — the `ModelOption` schema's fields, in its order."""

    id: str
    name: str
    status: Literal["current", "legacy", "retired", "new"]
    speed: Speed | None
    cost_level: int | None
    summary: str | None
    note: str | None
    successor: str | None
    forced_tool: bool
    available: bool | None
    retires_after: date | None


@dataclass(frozen=True)
class ModelOptions:
    default_model_id: str
    live: bool
    checked_at: datetime | None
    live_error: str | None
    models: list[ModelOption]


def _catalog_option(entry: CatalogModel, shown_id: str, available: bool | None) -> ModelOption:
    return ModelOption(
        id=shown_id, name=entry.name, status=entry.status, speed=entry.speed,
        cost_level=entry.cost_level, summary=entry.summary, note=entry.note,
        successor=entry.successor, forced_tool=entry.forced_tool, available=available,
        retires_after=date.fromisoformat(entry.retires_after) if entry.retires_after else None,
    )


def _new_models(live: Iterable[LiveModel]) -> list[LiveModel]:
    """Live models the catalog does not know that can read a photo, newest first.

    A dated id whose bare alias is listed too is the same model twice, and
    shows once, under the alias.
    """
    unknown = [m for m in live if lookup(m.id) is None and m.image_input]
    bare = {m.id for m in unknown}
    kept = [m for m in unknown if _undated(m.id) not in bare]
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(kept, key=lambda m: m.created_at or epoch, reverse=True)


def merged_options(
    listing: LiveListing,
    *,
    default_model_id: str,
    active_model_id: str | None = None,
) -> ModelOptions:
    """The catalog, overlaid with what Anthropic lists live.

    Every catalog entry is always present — retired ones too; the picker
    decides what to show. With a live list, a catalog entry is `available`
    when ANY of its ids is listed, and a listed model the catalog lacks is
    added as `new` if it takes images (a text-only model cannot analyze a
    hat). Without one, `available` is None: unknown, not false.

    `active_model_id` is the id this install actually sends. When it is an
    alias of a catalog entry — the dated Haiku id the old picker saved, say —
    that entry carries the alias as its `id`, so the saved choice is the
    option it names instead of an unrecognized id beside a second Haiku.

    Order: current, then new (newest first), then legacy, then retired.
    `forced_tool` on a `new` entry is False by construction — anything the
    allow-list accepts, dated or not, resolves to a catalog entry first.
    """
    live = listing.models
    live_ids = {m.id for m in live} if live is not None else set()
    active_entry = lookup(active_model_id) if active_model_id else None

    by_status: dict[str, list[ModelOption]] = {"current": [], "legacy": [], "retired": []}
    for entry in CATALOG:
        shown = active_model_id if active_entry is entry and active_model_id else entry.id
        available = None if live is None else any(lookup(i) is entry for i in live_ids)
        by_status[entry.status].append(_catalog_option(entry, shown, available))

    new = [
        ModelOption(
            # Nothing curated to say about a model this build has never seen;
            # `status: "new"` is the whole story, and the picker words it.
            id=m.id, name=m.display_name, status="new", speed=None, cost_level=None,
            summary=None, note=None, successor=None, forced_tool=False, available=True,
            retires_after=None,
        )
        for m in _new_models(live or ())
    ]

    return ModelOptions(
        default_model_id=default_model_id,
        live=live is not None,
        checked_at=listing.checked_at,
        live_error=listing.error,
        models=[*by_status["current"], *new, *by_status["legacy"], *by_status["retired"]],
    )


async def model_options(
    api_key: str | None, *, active_model_id: str | None = None, refresh: bool = False
) -> ModelOptions:
    """`GET /api/settings/models`: the merged list for this install's key and model."""
    listing = await get_live_listing(api_key, refresh=refresh)
    return merged_options(
        listing,
        default_model_id=config_settings.anthropic_model,
        active_model_id=active_model_id,
    )
