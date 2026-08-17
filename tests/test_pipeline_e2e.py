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

    async def _fake_analyze(_image_path, _api_key, model=None, selected_style=None):  # noqa: ARG001
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
    assert data["model_name"] == "A-Game Hydro"
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

    async def _boom(_path, _key, model=None, selected_style=None):  # noqa: ARG001
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
async def test_claude_corrects_construction_but_silence_changes_nothing(client):
    """A real identification wins; a non-answer leaves the record alone.

    Corrective since 2.11, where construction became free-form text. It used to
    be additive-only, because with two booleans and no way to say "standard"
    there was no distinction between "this is not HYDROLite" and "I can't see
    whether it is" — so clearing risked un-ticking a box the owner set while
    holding the hat. Naming a fabric is a positive identification, so it now
    overwrites; silence still does not.
    """
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import _apply_construction

    hat = Hat()
    hat.set_construction("HYDROLite")

    # Null is "I can't tell" — absence of evidence, not evidence of absence.
    _apply_construction(hat, None)
    assert hat.construction == "HYDROLite"
    assert hat.hydrolite is True

    # So is the old enum's "I can't tell" member, which must never be stored as
    # if it were a fabric.
    _apply_construction(hat, "standard")
    assert hat.construction == "HYDROLite", "'standard' is a non-answer, not a fabric"
    assert hat.hydrolite is True

    # A named fabric corrects the record — and the derived flags follow it,
    # rather than being left behind describing the previous answer.
    _apply_construction(hat, "Thermal")
    assert hat.construction == "Thermal"
    assert hat.hydrolite is False and hat.hydro is False


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
