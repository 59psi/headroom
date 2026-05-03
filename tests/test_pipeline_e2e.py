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

    `analyze_hat_image` and `settings_service` are bound by name in two
    modules (the pipeline + the reanalyze route handler). We patch both
    so either entry point exercises the stub.
    """
    async def _fake_get_key(_db):
        return "sk-ant-test-fixture", "database"

    async def _fake_analyze(_image_path, _api_key):
        return HatAnalysis(
            brand="Melin",
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
    # Patch both name-bindings of analyze_hat_image (pipeline + reanalyze route).
    monkeypatch.setattr(
        "headroom.services.hat_analysis_pipeline.analyze_hat_image", _fake_analyze
    )
    monkeypatch.setattr(
        "headroom.routes.hats.analyze_hat_image", _fake_analyze
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

    async def _boom(_path, _key):
        raise ClaudeAnalysisError("Invalid Anthropic API key.")

    monkeypatch.setattr(
        "headroom.services.settings_service.get_anthropic_key", _fake_get_key
    )
    monkeypatch.setattr(
        "headroom.services.hat_analysis_pipeline.analyze_hat_image", _boom
    )
    monkeypatch.setattr(
        "headroom.routes.hats.analyze_hat_image", _boom
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
