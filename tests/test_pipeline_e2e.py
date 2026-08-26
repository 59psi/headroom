"""End-to-end test of the photo upload pipeline with Claude analysis mocked.

This is the test the v0.2.0 release was missing — it exercises the full
upload → bg-removal → Claude → DB write path with a stubbed Claude response,
proving that the orchestration plumbing actually wires together. A regression
in any of the pipeline boundaries (Anthropic SDK contract, color persistence,
Melin pointer logic, status transitions) trips this test.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from headroom.services.claude_analysis import AnalyzedColor, HatAnalysis


def _jpeg(color=(0, 0, 200)) -> io.BytesIO:
    img = Image.new("RGB", (200, 200), color)
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    buf.seek(0)
    return buf


@pytest.fixture
def stub_claude(monkeypatch):
    """Patch Claude analysis + force a configured key so the pipeline runs.

    `analyze_hat_image` is bound in one place — the pipeline module — for both
    the upload and reanalyze paths (the route delegates to
    `reanalyze_existing_photo`), so a single patch covers both entry points.
    """
    async def _fake_get_key(_db):
        return "sk-ant-test-fixture", "database"

    async def _fake_analyze(_image_path, _api_key, model=None, selected_style=None, **_kw):  # noqa: ARG001
        return HatAnalysis(
            brand="Melin",
            logo_detected="Melin — M monogram, front panel",
            model_name="A-Game Hydro",
            model_confidence="high",
            style_descriptor="fitted snapback",
            design_notes="Clean 6-panel snapback with embroidered icon at front.",
            estimated_new_price_usd=60.0,
            colors=[
                AnalyzedColor(name="navy", hex="#1c2541", tier="primary"),
                AnalyzedColor(name="white", hex="#f5f5f5", tier="secondary"),
            ],
            raw=None,
        )

    # Patch the source — `settings_service` is imported as a module everywhere,
    # so attribute reassignment propagates to all callers.
    monkeypatch.setattr(
        "headroom.services.settings_service.get_anthropic_key", _fake_get_key
    )
    # Single seam: both upload and reanalyze route through the pipeline module.
    monkeypatch.setattr(
        "headroom.services.hat_analysis_pipeline.analyze_hat_image", _fake_analyze
    )


@pytest.mark.anyio
async def test_upload_persists_full_claude_analysis(client, stub_claude):
    """Happy path: upload → photo saved → all Claude fields populated → Melin link."""
    create = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game"},
    )
    hat_id = create.json()["id"]

    resp = await client.post(
        f"/api/hats/{hat_id}/photo",
        files={"photo": ("hat.jpg", _jpeg(), "image/jpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()

    # Photo persisted
    assert data["photo_path"] is not None
    assert data["photo_path"].startswith("hats/")

    # Analysis succeeded and populated structured fields
    assert data["analysis_status"] == "ok"
    assert data["analysis_error"] is None
    assert data["analyzed_at"] is not None
    assert data["brand"] == "Melin"
    # Records what was SEEN, separately from `brand`, which may be inferred.
    assert data["logo_detected"] == "Melin — M monogram, front panel"
    # "A-Game Hydro" comes back as "A-Game": the fixture states no construction,
    # and analysis is no longer allowed to assert one — in `construction` or,
    # as here, inside the model name. Stating HYDRO and re-analyzing restores
    # the full name.
    assert data["model_name"] == "A-Game"
    assert data["construction"] is None, "analysis decided a construction"
    assert data["model_confidence"] == "high"
    assert data["style_descriptor"] == "fitted snapback"
    assert data["estimated_new_price"] == 60.0
    assert data["estimated_new_price_source"] == "Claude Vision"

    # Colors landed in dominance order with tiers preserved
    assert len(data["colors"]) == 2
    assert data["colors"][0]["color_name"] == "navy"
    assert data["colors"][0]["hex_value"] == "#1c2541"
    assert data["colors"][0]["tier"] == "primary"
    assert data["colors"][0]["dominance_rank"] == 1
    assert data["colors"][1]["dominance_rank"] == 2
    assert data["colors"][1]["tier"] == "secondary"

    # Melin pointer wired up because brand=Melin
    assert data["resale_price_source"] == "Melin Recap"
    assert data["resale_price_url"] is not None
    assert "melinrecap.com" in data["resale_price_url"]
    assert "pub_category=aGame" in data["resale_price_url"]


@pytest.mark.anyio
async def test_reanalyze_overwrites_previous_analysis(client, stub_claude):
    """POST /reanalyze re-runs Claude on the existing photo and updates fields."""
    create = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game"},
    )
    hat_id = create.json()["id"]

    # Initial upload populates analysis
    await client.post(
        f"/api/hats/{hat_id}/photo",
        files={"photo": ("hat.jpg", _jpeg(), "image/jpeg")},
    )

    resp = await client.post(f"/api/hats/{hat_id}/reanalyze")
    assert resp.status_code == 200
    data = resp.json()
    assert data["analysis_status"] == "ok"
    assert data["brand"] == "Melin"


@pytest.mark.anyio
async def test_claude_error_marks_hat_status_error(client, monkeypatch):
    """If Claude raises, status='error' + analysis_error is set; photo still saves."""
    from headroom.services.claude_analysis import ClaudeAnalysisError

    async def _fake_get_key(_db):
        return "sk-ant-fixture", "database"

    async def _boom(_path, _key, model=None, selected_style=None, **_kw):  # noqa: ARG001
        raise ClaudeAnalysisError("Invalid Anthropic API key.")

    monkeypatch.setattr(
        "headroom.services.settings_service.get_anthropic_key", _fake_get_key
    )
    monkeypatch.setattr(
        "headroom.services.hat_analysis_pipeline.analyze_hat_image", _boom
    )

    create = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game"},
    )
    hat_id = create.json()["id"]

    resp = await client.post(
        f"/api/hats/{hat_id}/photo",
        files={"photo": ("hat.jpg", _jpeg(), "image/jpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["photo_path"] is not None  # Photo still saved
    assert data["analysis_status"] == "error"
    assert "Invalid Anthropic API key" in data["analysis_error"]
    assert data["colors"] == []


@pytest.mark.anyio
async def test_analysis_never_writes_a_construction_at_all(client):
    """Construction is owner-only. Analysis does not get a vote.

    2.11 let a named fabric overwrite what was on record and that was reverted,
    because Claude reads HYDRO vs HYDROLite off one photo unreliably — the
    tells are bonded seams, a gel-welded logo and a sweatband, none of which
    survive a front-on shot. What survived that revert was permission to fill a
    *blank*, which is the same coin toss with nothing prior to notice being
    lost.

    Two things made that expensive rather than cosmetic: `retail_pricing`
    prices HYDRO at $79 and HYDROLite at $99, so a guess skewing HYDROLite
    over-prices the hat; and construction became a filter, so a mislabeled hat
    is absent from a filtered view rather than merely wrong in a detail pane.

    A blank construction is an honest "nobody has looked yet". A guessed one is
    indistinguishable from one the owner typed.
    """
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import _apply_construction

    # Empty stays empty — this is the change.
    blank = Hat()
    _apply_construction(blank, "HYDROLite")
    assert blank.construction is None, "analysis decided a construction"
    # `not`, not `is False`: column defaults are applied on flush, so an
    # unsaved Hat() carries None here rather than False.
    assert not blank.hydrolite
    assert not blank.hydro

    # Already stated: still untouchable.
    owned = Hat()
    owned.set_construction("Waxed Canvas")
    _apply_construction(owned, "HYDRO")
    assert owned.construction == "Waxed Canvas", "analysis overrode the owner"
    assert owned.hydro is False

    # Non-answers were never written and still aren't.
    empty = Hat()
    _apply_construction(empty, None)
    _apply_construction(empty, "standard")
    assert empty.construction is None


@pytest.mark.anyio
async def test_construction_flags_are_derived_not_assigned(client):
    """`hydro`/`hydrolite` are an index over the text, so they can't disagree.

    They stay real columns because search filters query them, which is exactly
    what makes drift dangerous: a hat reading "Thermal" that still matches a
    HYDRO filter is wrong in the one place the flags exist to serve.
    """
    from headroom.models.hat import Hat

    hat = Hat()

    # Substring, not equality — real answers arrive as product names.
    hat.set_construction("A-Game Hydro")
    assert hat.hydro is True and hat.hydrolite is False

    # HYDROLite contains "hydro"; the more specific answer must win.
    hat.set_construction("HYDROLite")
    assert hat.hydrolite is True and hat.hydro is False

    # An unrelated fabric clears both rather than leaving a stale one set.
    hat.set_construction("Corduroy")
    assert hat.hydro is False and hat.hydrolite is False

    # Blank means "not stated", not the empty string.
    hat.set_construction("   ")
    assert hat.construction is None


@pytest.mark.anyio
async def test_analysis_never_erases_a_typed_identity(client):
    """A null from Claude must not wipe brand / model / artist the owner typed.

    The tool schema tells Claude to answer null rather than guess, and it says
    so most forcefully for `artist_series` ("guessing here is worse than
    leaving it empty"). Special editions are exactly the hats Claude is least
    able to name and the owner most wants recorded, so passing that null
    through would erase the field every time they tapped Reanalyze — the same
    "absence of evidence isn't evidence of absence" rule the construction
    flags follow above.
    """
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import _apply_analysis

    hat = Hat(brand="melin", model_name="Coronado", artist_series="Skye Walker")

    _apply_analysis(
        hat,
        HatAnalysis(
            brand=None,
            model_name=None,
            model_confidence="low",
            style_descriptor="fitted snapback",
            design_notes="Could not identify.",
            estimated_new_price_usd=None,
            artist_series=None,
            colors=[],
        ),
    )

    assert hat.artist_series == "Skye Walker", "a null answer must not erase the collab"
    assert hat.brand == "melin"
    assert hat.model_name == "Coronado"


@pytest.mark.anyio
async def test_analysis_still_overwrites_with_a_real_answer(client):
    """The guard only blocks erasure — Claude can still correct itself."""
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import _apply_analysis

    hat = Hat(brand="melin", model_name="Coronado", artist_series="Skye Walker")

    _apply_analysis(
        hat,
        HatAnalysis(
            brand="New Era",
            model_name="59FIFTY",
            model_confidence="high",
            style_descriptor="fitted",
            design_notes="Wool fitted cap.",
            estimated_new_price_usd=45.0,
            artist_series="melin x OluKai",
            colors=[],
        ),
    )

    assert hat.artist_series == "melin x OluKai"
    assert hat.brand == "New Era"
    assert hat.model_name == "59FIFTY"


@pytest.mark.anyio
async def test_patch_hat_round_trips_artist_series(client):
    """The Edit Hat form's new Artist / Collab field must persist and read back."""
    create = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "collab"},
    )
    hat_id = create.json()["id"]
    assert create.json()["artist_series"] is None

    resp = await client.put(
        f"/api/hats/{hat_id}", json={"artist_series": "melin x Austin Gamblers"}
    )
    assert resp.status_code == 200
    assert resp.json()["artist_series"] == "melin x Austin Gamblers"

    fetched = await client.get(f"/api/hats/{hat_id}")
    assert fetched.json()["artist_series"] == "melin x Austin Gamblers"


@pytest.mark.anyio
async def test_the_owner_stated_construction_is_sent_to_claude(client, monkeypatch):
    """It has to be IN the prompt, not merely protected from being overwritten.

    2.12 stopped analysis writing over a stated construction, but never told it
    what the owner had said — so a hat recorded as Thermal still came back
    named "A-Game HYDROLite". The value being safe in the database doesn't help
    when the wrong build is baked into `model_name`, which is the field a
    person actually reads.
    """
    from headroom.services.claude_analysis import _owner_context

    seen: dict = {}

    async def _fake_get_key(_db):
        return "sk-ant-fixture", "database"

    async def _capture(_path, _key, model=None, selected_style=None, **kw):  # noqa: ARG001
        seen["style"] = selected_style
        seen["construction"] = kw.get("selected_construction")
        # A complete value: an incomplete one raises inside the pipeline's
        # try/except, which would leave this test passing on a swallowed error
        # rather than on a successful run.
        return HatAnalysis(
            brand="Melin", model_name="Trenches Thermal", model_confidence="high",
            style_descriptor=None, design_notes=None, estimated_new_price_usd=None,
            colors=[], raw=None,
        )

    monkeypatch.setattr(
        "headroom.services.settings_service.get_anthropic_key", _fake_get_key
    )
    monkeypatch.setattr(
        "headroom.services.hat_analysis_pipeline.analyze_hat_image", _capture
    )

    created = await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "trenches",
        "construction": "Thermal",
    })
    hat_id = created.json()["id"]
    await client.post(
        f"/api/hats/{hat_id}/photo", files={"photo": ("h.jpg", _jpeg(), "image/jpeg")}
    )

    assert seen["construction"] == "Thermal", "the owner's construction never reached Claude"
    assert seen["style"] == "trenches"

    hat = (await client.get(f"/api/hats/{hat_id}")).json()
    assert hat["analysis_status"] == "ok", hat["analysis_error"]
    assert hat["construction"] == "Thermal"
    assert hat["model_name"] == "Trenches Thermal"

    # And the prompt actually states it as binding, including for model_name.
    prompt = _owner_context("trenches", "Thermal")
    assert "Thermal" in prompt
    assert "Trenches" in prompt
    assert "model_name" in prompt


@pytest.mark.anyio
async def test_no_owner_context_when_nothing_was_stated(client):
    """A blank construction must not put an empty claim in the prompt."""
    from headroom.services.claude_analysis import _owner_context

    assert _owner_context(None, None) == "Analyze this hat photo using the tool."
    # Beanie is excluded from the style claim (it is a shape, not a melin line),
    # so on its own it produces no owner context either.
    assert _owner_context("beanie", None) == "Analyze this hat photo using the tool."

    # Construction alone is still worth stating.
    assert "Thermal" in _owner_context(None, "Thermal")


@pytest.mark.anyio
async def test_a_rescan_repairs_a_model_name_that_contradicts_the_construction(client):
    """melin names read "<line> <construction>", so a model name asserts a build.

    Hats analyzed before the owner's construction was sent to Claude kept names
    like "A-Game HYDROLite" on a hat recorded as Thermal — the construction
    field right, the name a person reads wrong. A full rescan has to repair
    those, not preserve them.
    """
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import (
        _apply_analysis,
        _strip_contradicting_construction,
    )

    # Removed, not rewritten: "A-Game Thermal" would be inventing a product
    # name, where "A-Game" is merely less specific and true.
    assert _strip_contradicting_construction("A-Game HYDROLite", "Thermal") == "A-Game"
    assert _strip_contradicting_construction("Trenches Icon Hydro", "Thermal") == "Trenches Icon"

    # A name that agrees is left exactly as it is.
    assert _strip_contradicting_construction("Coronado HYDROLite", "HYDROLite") == "Coronado HYDROLite"
    assert _strip_contradicting_construction("A-Game Hydro", "HYDRO") == "A-Game Hydro"

    # Word boundaries: HYDRO must not match inside HYDROLite, or a genuine
    # HYDROLite hat would end up reading "Coronado Lite".
    assert _strip_contradicting_construction("Coronado HYDROLite", "Waxed Canvas") == "Coronado"

    # Nothing stated means nothing may be claimed. This used to leave the name
    # alone, which quietly parked Claude's construction guess in `model_name` —
    # the field a person actually reads — while `construction` stayed blank.
    # Analysis no longer decides construction at all, and a name asserting one
    # is that same decision in a different column.
    assert _strip_contradicting_construction("A-Game HYDROLite", None) == "A-Game"
    assert _strip_contradicting_construction("Trenches Icon Hydro", None) == "Trenches Icon"
    # A name carrying no construction is untouched either way.
    assert _strip_contradicting_construction("Coronado Rope", None) == "Coronado Rope"
    assert _strip_contradicting_construction(None, "Thermal") is None

    # And it runs on the analysis path, so a rescan fixes stored rows even when
    # Claude returns no model name of its own.
    hat = Hat()
    hat.set_construction("Thermal")
    hat.model_name = "A-Game HYDROLite"
    _apply_analysis(hat, HatAnalysis(
        brand="Melin", model_name=None, model_confidence="low",
        style_descriptor=None, design_notes=None, estimated_new_price_usd=None,
        colors=[], raw=None,
    ))

    assert hat.model_name == "A-Game", "the rescan preserved the contradicting name"
