"""The model catalog, the live Models API merge, its cache, and the route.

`model_catalog.CATALOG` is the one table of Claude models: the Settings picker
reads it through `GET /api/settings/models`, and `claude_analysis` derives its
forced-tool allow-list from it. Those were two hand-kept lists, and a model
added to one was a model missing from the other — Fable 5.1 sat on the roster
as "most capable" while every analysis sent it a tool choice it refuses.

The live half runs through the REAL SDK against `httpx2.MockTransport`, as
`test_claude_call_shape` does for the analysis call: pagination and the
`capabilities` object (a pydantic model, not a dict) are exactly where a
hand-written fake would agree with our code and the SDK would not.
"""

from __future__ import annotations

import asyncio
import json
import re
import typing
from datetime import date, datetime, timezone
from pathlib import Path

import httpx2
import pytest
from anthropic import AsyncAnthropic

from headroom.config import Settings, settings
from headroom.schemas.settings import ModelOption as ModelOptionSchema
from headroom.services import claude_analysis, model_catalog
from headroom.services.model_catalog import CATALOG, LiveListing, LiveModel

pytestmark = pytest.mark.anyio

#: conftest replaces the seam with a refusal for the whole suite. Captured at
#: import — before any fixture runs — so the SDK-level tests below exercise
#: the real function.
_REAL_LIST_LIVE_MODELS = model_catalog.list_live_models

_CONTRACT_OPTION_KEYS = {
    "id", "name", "status", "speed", "cost_level", "summary", "note",
    "successor", "forced_tool", "available", "retires_after",
}
_CONTRACT_KEYS = {"default_model_id", "live", "checked_at", "live_error", "models"}

_ZONED = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"


def _entry(model_id: str) -> model_catalog.CatalogModel:
    entry = model_catalog.lookup(model_id)
    assert entry is not None, model_id
    return entry


def _live(*models: LiveModel) -> LiveListing:
    return LiveListing(models=models, checked_at=datetime.now(timezone.utc))


def _lm(model_id: str, *, image: bool = True, name: str | None = None,
        created: datetime | None = None) -> LiveModel:
    return LiveModel(id=model_id, display_name=name or model_id, created_at=created,
                     image_input=image)


def _by_id(options: model_catalog.ModelOptions) -> dict[str, model_catalog.ModelOption]:
    return {m.id: m for m in options.models}


# ---- the table itself ---------------------------------------------------- #


async def test_no_id_names_two_models():
    """A dated id listed under two entries would resolve to whichever came
    first, and the picker would show one model twice."""
    ids = [mid for m in CATALOG for mid in m.ids]
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)


async def test_every_superseded_model_points_at_a_current_one():
    current = {m.id for m in CATALOG if m.status == "current"}
    for m in CATALOG:
        if m.status == "current":
            assert m.successor is None, f"{m.id} is current yet names a successor"
        else:
            assert m.successor in current, f"{m.id} -> {m.successor!r}, not a current id"


async def test_the_current_lineup_is_the_verified_one():
    current = {m.id: m for m in CATALOG if m.status == "current"}
    assert set(current) == {
        "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-haiku-4-5",
    }
    # These three answer a forced tool choice with a 400; Haiku accepts it.
    assert {mid for mid, m in current.items() if not m.forced_tool} == {
        "claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5",
    }
    assert {mid: m.speed for mid, m in current.items()} == {
        "claude-haiku-4-5": "Fastest", "claude-sonnet-5-5": "Fast",
        "claude-opus-5-5": "Moderate", "claude-fable-5-1": "Slower",
    }
    assert current["claude-haiku-4-5"].retires_after == "2026-10-15"
    assert "claude-haiku-4-5-20251001" in current["claude-haiku-4-5"].aliases
    for m in current.values():
        assert m.summary, f"{m.id} has no label phrase"


async def test_cost_levels_follow_the_family():
    family = {"haiku": 1, "sonnet": 2, "opus": 3, "fable": 5}
    for m in CATALOG:
        if m.status == "retired":
            assert m.cost_level is None, m.id
            continue
        (fam,) = [f for f in family if f in m.id]
        assert m.cost_level == family[fam], m.id


async def test_every_label_phrase_fits_the_picker():
    """The picker renders "<name> — <summary>" and appends " (default)" to
    the default. "— the default" in a summary read "the default (default)",
    and would name the wrong model once HEADROOM_ANTHROPIC_MODEL moved it;
    "Previous generation" on nine legacy options repeated the group they sit
    in; and a sentence-long phrase ends in "…" on a phone's closed select."""
    for m in CATALOG:
        if m.status != "current":
            assert m.summary is None, f"{m.id}: the status already says {m.summary!r}"
            continue
        assert m.summary, f"{m.id} has no label phrase"
        assert len(m.summary) <= 30, f"{m.id}: {m.summary!r} is a sentence, not a phrase"
        assert "default" not in m.summary.lower(), f"{m.id}: {m.summary!r}"


async def test_every_retirement_date_is_a_date():
    for m in CATALOG:
        if m.retires_after is not None:
            date.fromisoformat(m.retires_after)


async def test_retired_ids_are_the_ones_anthropic_404s():
    retired = {mid for m in CATALOG if m.status == "retired" for mid in m.ids}
    assert retired >= {
        "claude-opus-4-1", "claude-opus-4-0", "claude-opus-4-20250514",
        "claude-sonnet-4-0", "claude-sonnet-4-20250514", "claude-3-7-sonnet-20250219",
        "claude-3-5-haiku-20241022", "claude-3-opus-20240229",
        "claude-3-5-sonnet-20241022", "claude-3-5-sonnet-20240620", "claude-3-haiku-20240307",
    }


async def test_the_built_in_default_is_sonnet_5_5_and_current():
    """The built-in default only — a saved choice still outranks it."""
    assert Settings.model_fields["anthropic_model"].default == "claude-sonnet-5-5"
    assert _entry(settings.anthropic_model).status == "current"


async def test_a_saved_model_outranks_the_new_default(client):
    """Existing installs that picked a model keep it across the default change."""
    await client.put("/api/settings/model", json={"model_id": "claude-sonnet-5"})
    body = (await client.get("/api/settings/model")).json()
    assert body["model_id"] == "claude-sonnet-5"
    assert body["default_model_id"] == "claude-sonnet-5-5"


# ---- one table: the analysis request reads the same flags ---------------- #


async def test_the_forced_tool_allow_list_is_derived_from_the_catalog():
    expected = {mid for m in CATALOG if m.forced_tool for mid in m.ids}
    assert set(claude_analysis._FORCED_TOOL_CHOICE_MODELS) == expected


#: The hand-kept allow-list the table replaced, as 2.82.2 shipped it, spelled
#: out as the ids Anthropic actually serves. Its bare `claude-opus-4` and
#: `claude-sonnet-4` were never model ids — they sat there so the date rule
#: would reach `claude-opus-4-20250514` — and the table names those dated
#: ids outright, so they are pinned here instead.
_FORCED_BEFORE_THE_TABLE = (
    "claude-sonnet-5", "claude-opus-5", "claude-fable-5",
    "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6",
    "claude-opus-4-5", "claude-opus-4-5-20251101",
    "claude-sonnet-4-5", "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5", "claude-haiku-4-5-20251001",
    "claude-opus-4-1", "claude-opus-4-20250514", "claude-sonnet-4-20250514",
)


@pytest.mark.parametrize("model_id", _FORCED_BEFORE_THE_TABLE)
async def test_every_model_the_old_list_forced_is_still_forced(model_id):
    """Each of these was verified to accept a forced tool choice. Deriving
    the allow-list must not quietly move one to `auto`: its analyses would
    lose the structured-answer guarantee and get an 8x output ceiling, with
    every other test green — the derivation test and the request-builder
    test both read the same flag, so a flipped flag agrees with itself."""
    assert claude_analysis._accepts_forced_tool_choice(model_id) is True


@pytest.mark.parametrize("model_id", [mid for m in CATALOG for mid in m.ids])
async def test_the_request_builder_agrees_with_every_catalog_id(model_id):
    """Canonical ids and aliases alike: what the picker says a model accepts
    is what the analysis request sends it."""
    forced = claude_analysis._analysis_request(model_id, [])["tool_choice"]["type"] == "tool"
    assert forced is _entry(model_id).forced_tool


@pytest.mark.parametrize(
    ("model_id", "forced"),
    [
        # The new default and its generation: `auto`, or every hat fails.
        ("claude-sonnet-5-5", False),
        ("claude-opus-5-5", False),
        ("claude-fable-5-1", False),
        # The dated alias the old picker saved still gets the forced call.
        ("claude-haiku-4-5-20251001", True),
        ("claude-haiku-4-5", True),
        # A dated snapshot of a listed model is that model...
        ("claude-sonnet-5-20260101", True),
        # ...but a non-date suffix is a different model.
        ("claude-sonnet-5-55555555x", False),
    ],
)
async def test_the_date_suffix_rule_survives_the_derivation(model_id, forced):
    assert claude_analysis._accepts_forced_tool_choice(model_id) is forced


async def test_lookup_resolves_aliases_and_dated_snapshots_but_not_near_misses():
    assert _entry("claude-haiku-4-5-20251001").id == "claude-haiku-4-5"
    assert _entry("claude-opus-4-20250514").id == "claude-opus-4-0"
    assert _entry("claude-sonnet-5-5-20261201").id == "claude-sonnet-5-5"
    # Opus 5.5 is not a dated Opus 5.
    assert _entry("claude-opus-5-5").id == "claude-opus-5-5"
    assert model_catalog.lookup("claude-someday-9") is None


# ---- merging the live list ----------------------------------------------- #


async def test_without_a_live_list_the_whole_catalog_comes_back_unchecked():
    opts = model_catalog.merged_options(
        LiveListing(models=None, error="nope"), default_model_id="claude-sonnet-5-5",
    )
    assert opts.live is False and opts.live_error == "nope" and opts.checked_at is None
    assert [m.id for m in opts.models] == [m.id for m in CATALOG]
    assert all(m.available is None for m in opts.models)


async def test_a_new_image_model_is_offered_and_a_text_only_one_is_not():
    opts = model_catalog.merged_options(
        _live(
            _lm("claude-sonnet-5-5"),
            _lm("claude-verse-6", name="Claude Verse 6"),
            _lm("claude-textonly-6", image=False),
        ),
        default_model_id="claude-sonnet-5-5",
    )
    by_id = _by_id(opts)
    assert opts.live is True
    new = by_id["claude-verse-6"]
    assert (new.status, new.name, new.available, new.forced_tool) == (
        "new", "Claude Verse 6", True, False,
    )
    assert "claude-textonly-6" not in by_id


async def test_a_catalog_model_the_key_cannot_see_is_unavailable():
    by_id = _by_id(model_catalog.merged_options(
        _live(_lm("claude-sonnet-5-5")), default_model_id="claude-sonnet-5-5",
    ))
    assert by_id["claude-sonnet-5-5"].available is True
    assert by_id["claude-opus-5-5"].available is False
    # Retired models are always present — the picker decides whether to show.
    assert by_id["claude-3-haiku-20240307"].available is False
    assert by_id["claude-3-haiku-20240307"].status == "retired"


async def test_a_dated_live_id_is_its_catalog_entry_not_a_new_model():
    opts = model_catalog.merged_options(
        _live(
            _lm("claude-haiku-4-5-20251001", name="Claude Haiku 4.5"),
            _lm("claude-opus-4-5-20251101"),
            # A snapshot this build has no alias for still folds by its date.
            _lm("claude-sonnet-5-5-20261201"),
        ),
        default_model_id="claude-sonnet-5-5",
    )
    by_id = _by_id(opts)
    assert by_id["claude-haiku-4-5"].available is True
    assert by_id["claude-opus-4-5"].available is True
    assert by_id["claude-sonnet-5-5"].available is True
    assert not [m for m in opts.models if m.status == "new"]
    assert sum(m.name == "Claude Haiku 4.5" for m in opts.models) == 1


async def test_a_new_models_dated_and_bare_ids_are_one_entry():
    opts = model_catalog.merged_options(
        _live(_lm("claude-verse-6-20261101"), _lm("claude-verse-6")),
        default_model_id="claude-sonnet-5-5",
    )
    assert [m.id for m in opts.models if m.status == "new"] == ["claude-verse-6"]


async def test_the_saved_alias_is_the_id_its_entry_carries():
    """The old picker saved Haiku's dated id. That install must see its choice
    as the Haiku option, not as an unknown id beside a second Haiku."""
    opts = model_catalog.merged_options(
        LiveListing(models=None), default_model_id="claude-sonnet-5-5",
        active_model_id="claude-haiku-4-5-20251001",
    )
    haikus = [m for m in opts.models if m.name == "Claude Haiku 4.5"]
    assert [m.id for m in haikus] == ["claude-haiku-4-5-20251001"]
    # Anyone else gets the canonical id.
    plain = model_catalog.merged_options(
        LiveListing(models=None), default_model_id="claude-sonnet-5-5",
        active_model_id="claude-opus-5-5",
    )
    assert "claude-haiku-4-5" in _by_id(plain)


async def test_the_order_is_current_new_legacy_retired():
    opts = model_catalog.merged_options(
        _live(
            _lm("claude-verse-6", created=datetime(2026, 9, 1, tzinfo=timezone.utc)),
            _lm("claude-verse-7", created=datetime(2026, 9, 20, tzinfo=timezone.utc)),
        ),
        default_model_id="claude-sonnet-5-5",
    )
    statuses = [m.status for m in opts.models]
    rank = {"current": 0, "new": 1, "legacy": 2, "retired": 3}
    assert statuses == sorted(statuses, key=rank.__getitem__)
    assert [m.id for m in opts.models if m.status == "new"] == ["claude-verse-7", "claude-verse-6"]


async def test_every_merged_entry_reports_what_the_request_builder_does():
    opts = model_catalog.merged_options(
        _live(_lm("claude-verse-6"), _lm("claude-haiku-4-5-20251001")),
        default_model_id="claude-sonnet-5-5", active_model_id="claude-haiku-4-5-20251001",
    )
    for m in opts.models:
        assert m.forced_tool is claude_analysis._accepts_forced_tool_choice(m.id), m.id


# ---- the live call, through the real SDK --------------------------------- #


def _capabilities(image: bool) -> dict:
    yes = {"supported": True}
    return {
        "batch": yes, "citations": yes, "code_execution": yes,
        "context_management": {"supported": True},
        "effort": {"supported": True, "low": yes, "medium": yes, "high": yes, "max": yes},
        "image_input": {"supported": image}, "pdf_input": yes, "structured_outputs": yes,
        "thinking": {"supported": True, "types": {"adaptive": yes, "enabled": yes}},
    }


def _model_row(model_id: str, name: str, *, image: bool | None = True) -> dict:
    return {
        "type": "model", "id": model_id, "display_name": name,
        "created_at": "2026-09-28T00:00:00Z",
        "max_input_tokens": 200_000, "max_tokens": 64_000,
        "capabilities": None if image is None else _capabilities(image),
    }


def _wire(monkeypatch, responder):
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return responder(request)

    def fake_client(api_key, timeout, **kw):
        return AsyncAnthropic(
            api_key=api_key, timeout=timeout, max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        )

    monkeypatch.setattr(claude_analysis, "_anthropic_client", fake_client)
    monkeypatch.setattr(model_catalog, "list_live_models", _REAL_LIST_LIVE_MODELS)
    return seen


async def test_every_page_is_read_and_image_support_comes_from_capabilities(monkeypatch):
    pages = {
        None: {
            "data": [
                _model_row("claude-sonnet-5-5", "Claude Sonnet 5.5"),
                _model_row("claude-textonly-6", "Text Only", image=False),
            ],
            "has_more": True, "first_id": "claude-sonnet-5-5", "last_id": "claude-textonly-6",
        },
        "claude-textonly-6": {
            "data": [_model_row("claude-verse-6", "Claude Verse 6"),
                     _model_row("claude-mystery-6", "Mystery", image=None)],
            "has_more": False, "first_id": "claude-verse-6", "last_id": "claude-mystery-6",
        },
    }
    seen = _wire(monkeypatch, lambda req: httpx2.Response(
        200, json=pages[req.url.params.get("after_id")]
    ))

    found = await model_catalog.list_live_models("sk-ant-test")

    assert [r.url.path for r in seen] == ["/v1/models", "/v1/models"]
    assert seen[1].url.params["after_id"] == "claude-textonly-6"
    assert {m.id: m.image_input for m in found} == {
        "claude-sonnet-5-5": True, "claude-textonly-6": False,
        "claude-verse-6": True, "claude-mystery-6": False,
    }
    assert found[0].display_name == "Claude Sonnet 5.5"
    assert found[0].created_at == datetime(2026, 9, 28, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("status", "error_type", "message"),
    [
        (401, "authentication_error", "Anthropic rejected the API key"),
        (403, "permission_error", "Anthropic answered 403"),
        (500, "api_error", "Anthropic answered 500"),
    ],
)
async def test_an_api_refusal_is_a_short_live_error(monkeypatch, status, error_type, message):
    _wire(monkeypatch, lambda req: httpx2.Response(status, json={
        "type": "error", "error": {"type": error_type, "message": "a long paragraph " * 20},
    }))

    listing = await model_catalog.get_live_listing("sk-ant-test")

    assert listing.models is None
    assert listing.error == message


async def test_an_unreachable_api_is_a_short_live_error(monkeypatch):
    def refuse(req):
        raise httpx2.ConnectError("no route to host", request=req)

    _wire(monkeypatch, refuse)
    listing = await model_catalog.get_live_listing("sk-ant-test")
    assert (listing.models, listing.error) == (None, "Could not reach Anthropic")


async def test_an_unexpected_failure_still_answers(monkeypatch):
    async def boom(_key):
        raise RuntimeError("something nobody planned for")

    monkeypatch.setattr(model_catalog, "list_live_models", boom)
    listing = await model_catalog.get_live_listing("sk-ant-test")
    assert listing.models is None
    assert listing.error == "Unexpected error listing models"


async def test_no_key_is_said_without_a_call(monkeypatch):
    calls: list[str] = []

    async def count(key):
        calls.append(key)
        return []

    monkeypatch.setattr(model_catalog, "list_live_models", count)
    for key in (None, ""):
        listing = await model_catalog.get_live_listing(key)
        assert (listing.models, listing.error) == (None, "No Claude API key configured")
    assert calls == []


# ---- the cache ----------------------------------------------------------- #


@pytest.fixture
def counted(monkeypatch):
    """A seam that answers one model and records which key asked."""
    calls: list[str] = []

    async def fake(key):
        calls.append(key)
        return [_lm("claude-sonnet-5-5")]

    monkeypatch.setattr(model_catalog, "list_live_models", fake)
    return calls


async def test_a_fresh_list_is_reused_and_refresh_bypasses_it(counted):
    first = await model_catalog.get_live_listing("sk-ant-one")
    again = await model_catalog.get_live_listing("sk-ant-one")
    assert counted == ["sk-ant-one"]
    assert again is first

    await model_catalog.get_live_listing("sk-ant-one", refresh=True)
    assert counted == ["sk-ant-one", "sk-ant-one"]


async def test_a_different_key_is_a_different_list(counted):
    await model_catalog.get_live_listing("sk-ant-one")
    await model_catalog.get_live_listing("sk-ant-two")
    assert counted == ["sk-ant-one", "sk-ant-two"]


async def test_two_page_loads_at_once_make_one_call(monkeypatch):
    """Two tabs opening Settings together, with nothing cached: the second
    waits for the first's answer instead of asking Anthropic again."""
    calls: list[str] = []
    release = asyncio.Event()

    async def slow(key):
        calls.append(key)
        await release.wait()
        return [_lm("claude-sonnet-5-5")]

    monkeypatch.setattr(model_catalog, "list_live_models", slow)
    first = asyncio.ensure_future(model_catalog.get_live_listing("sk-ant-one"))
    second = asyncio.ensure_future(model_catalog.get_live_listing("sk-ant-one"))
    while not calls:
        await asyncio.sleep(0)
    # The second load has now had its turn, and is waiting — on the lock,
    # or (the bug) on a fetch of its own.
    await asyncio.sleep(0)
    release.set()
    a, b = await asyncio.gather(first, second)

    assert calls == ["sk-ant-one"]
    assert a is b and a.models is not None


async def test_the_list_expires_after_six_hours(counted):
    await model_catalog.get_live_listing("sk-ant-one")
    model_catalog._cache.stored_at -= model_catalog.LIVE_TTL_S - 60
    await model_catalog.get_live_listing("sk-ant-one")
    assert len(counted) == 1, "still fresh a minute before the TTL"

    model_catalog._cache.stored_at -= 120
    await model_catalog.get_live_listing("sk-ant-one")
    assert len(counted) == 2


async def test_a_failure_is_retried_sooner_than_a_success(monkeypatch):
    calls: list[str] = []

    async def failing(key):
        calls.append(key)
        raise model_catalog.ModelListingError("Could not reach Anthropic")

    monkeypatch.setattr(model_catalog, "list_live_models", failing)
    await model_catalog.get_live_listing("sk-ant-one")
    await model_catalog.get_live_listing("sk-ant-one")
    assert len(calls) == 1, "a failure is held briefly, not refetched on every render"

    model_catalog._cache.stored_at -= model_catalog.FAILURE_TTL_S + 1
    await model_catalog.get_live_listing("sk-ant-one")
    assert len(calls) == 2
    assert model_catalog.FAILURE_TTL_S < model_catalog.LIVE_TTL_S


async def test_the_cache_holds_a_fingerprint_never_the_key(counted):
    key = "sk-ant-api03-very-secret-value"
    await model_catalog.get_live_listing(key)
    held = model_catalog._cache
    assert held.fingerprint != key and key not in repr(vars(held))
    assert key not in held.fingerprint


# ---- the route ----------------------------------------------------------- #


async def test_the_route_serves_the_contract_with_no_key(client):
    resp = await client.get("/api/settings/models")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == _CONTRACT_KEYS
    assert body["default_model_id"] == settings.anthropic_model == "claude-sonnet-5-5"
    assert (body["live"], body["checked_at"]) == (False, None)
    assert body["live_error"] == "No Claude API key configured"
    assert [m["id"] for m in body["models"]] == [m.id for m in CATALOG]
    for m in body["models"]:
        assert set(m) == _CONTRACT_OPTION_KEYS
        assert m["available"] is None
    haiku = next(m for m in body["models"] if m["id"] == "claude-haiku-4-5")
    assert haiku["retires_after"] == "2026-10-15"
    assert haiku["speed"] == "Fastest" and haiku["cost_level"] == 1
    sonnet = next(m for m in body["models"] if m["id"] == "claude-sonnet-5-5")
    assert sonnet["forced_tool"] is False and sonnet["status"] == "current"


async def test_the_route_merges_the_live_list_for_the_stored_key(client, monkeypatch):
    seen: list[str] = []

    async def fake(key):
        seen.append(key)
        return [_lm("claude-sonnet-5-5"), _lm("claude-verse-6", name="Claude Verse 6")]

    monkeypatch.setattr(model_catalog, "list_live_models", fake)
    await client.put("/api/settings/api-key", json={"api_key": "sk-ant-api03-route-key"})

    body = (await client.get("/api/settings/models")).json()

    assert seen == ["sk-ant-api03-route-key"]
    assert body["live"] is True and body["live_error"] is None
    assert re.match(_ZONED, body["checked_at"]), body["checked_at"]
    by_id = {m["id"]: m for m in body["models"]}
    assert by_id["claude-verse-6"]["status"] == "new"
    assert by_id["claude-sonnet-5-5"]["available"] is True
    assert by_id["claude-opus-5-5"]["available"] is False

    await client.get("/api/settings/models")
    assert len(seen) == 1, "cached"
    await client.get("/api/settings/models?refresh=1")
    assert len(seen) == 2, "?refresh=1 fetches again"


async def test_the_route_never_fails_on_a_live_error(client):
    """conftest's seam refuses; the page still gets the catalog."""
    await client.put("/api/settings/api-key", json={"api_key": "sk-ant-api03-route-key"})
    resp = await client.get("/api/settings/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["live"] is False
    assert body["live_error"] == "live model listing disabled in tests"
    assert len(body["models"]) == len(CATALOG)


async def test_the_route_names_the_saved_alias(client):
    await client.put("/api/settings/model", json={"model_id": "claude-haiku-4-5-20251001"})
    ids = [m["id"] for m in (await client.get("/api/settings/models")).json()["models"]]
    assert "claude-haiku-4-5-20251001" in ids and "claude-haiku-4-5" not in ids


async def test_the_route_is_gated(anon_client):
    assert (await anon_client.get("/api/settings/models")).status_code == 401


async def test_the_route_sends_nothing_raw_back(client, monkeypatch):
    """The live list is fetched WITH the key; nothing about the key comes back."""
    async def fake(_key):
        return [_lm("claude-sonnet-5-5")]

    monkeypatch.setattr(model_catalog, "list_live_models", fake)
    await client.put("/api/settings/api-key", json={"api_key": "sk-ant-api03-route-key"})
    text = (await client.get("/api/settings/models")).text
    assert "route-key" not in text
    assert json.loads(text)["live"] is True


# ---- the TypeScript mirror ----------------------------------------------- #

_TYPES = Path(__file__).resolve().parents[1] / "frontend" / "src" / "types" / "index.ts"


def _literal_values(annotation) -> set:
    """Every value a `Literal[...]` (or `Literal[...] | None`) admits, None aside."""
    if typing.get_origin(annotation) is typing.Literal:
        return set(typing.get_args(annotation))
    return {v for arg in typing.get_args(annotation) for v in _literal_values(arg)}


@pytest.mark.parametrize(
    ("field", "alias", "nullable"),
    [
        ("status", "ModelLifecycle", False),
        ("speed", "ModelSpeed", True),
        ("cost_level", "ModelCostLevel", True),
    ],
)
async def test_the_pickers_types_name_exactly_the_servers_values(field, alias, nullable):
    """`test_ts_schema_parity` holds fields and nullability, and
    `test_wire_vocabulary` holds unions spelled inline — these three are
    named type aliases, which neither reads. The card switches on `status`
    and draws `cost_level` marks, so a value added on one side only is a
    model the picker files nowhere or a meter it cannot draw."""
    src = _TYPES.read_text()
    declared = re.search(rf"export type {alias}\s*=\s*([^;]+);", src)
    assert declared, f"type {alias} not found in types/index.ts"
    ts_values = {
        int(tok) if tok.isdigit() else tok.strip("'")
        for tok in (t.strip() for t in declared.group(1).split("|"))
    }
    assert ts_values == _literal_values(ModelOptionSchema.model_fields[field].annotation)

    interface = re.search(r"export interface ModelOption \{(.*?)\n\}", src, re.S)
    assert interface, "interface ModelOption not found"
    typed = re.search(rf"^\s*{field}:\s*([^;]+);", interface.group(1), re.M)
    assert typed and typed.group(1).strip() == (f"{alias} | null" if nullable else alias)
