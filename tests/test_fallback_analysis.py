"""Tests for the no-Claude fallback: mask-based colors + Google logo brand.

No live APIs (house rule): Google Vision is exercised against canned JSON via
the `_annotate` seam; color extraction runs for real against synthetic RGBA
images so background rejection is actually proven, not stubbed.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from headroom.services.color_extraction import extract_hat_colors, nearest_color_name
from headroom.services.google_vision import GoogleVisionError, detect_brand_logo

pytestmark = pytest.mark.anyio


def _jpeg(color=(0, 0, 200)) -> io.BytesIO:
    img = Image.new("RGB", (200, 200), color)
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    buf.seek(0)
    return buf


def _cutout_png(path, hat_color=(200, 30, 30), second_color=None):
    """Synthetic rembg-style cutout: colored 'hat' on a transparent canvas.

    The transparent region deliberately has a garish RGB value underneath the
    zero alpha — if extraction ever reads unmasked pixels, green leaks in.
    """
    img = Image.new("RGBA", (100, 100), (0, 255, 0, 0))  # green, fully transparent
    for x in range(20, 80):
        for y in range(20, 80):
            img.putpixel((x, y), (*hat_color, 255))
    if second_color:
        for x in range(20, 80):
            for y in range(20, 35):
                img.putpixel((x, y), (*second_color, 255))
    img.save(path, "PNG")
    return path


# ------------------------- color extraction --------------------------- #


async def test_extract_colors_rejects_background(tmp_path):
    """Only alpha-masked hat pixels count — the green background never leaks."""
    png = _cutout_png(tmp_path / "hat.png", hat_color=(200, 30, 30))
    colors = extract_hat_colors(png)
    assert colors, "expected at least one color from the opaque region"
    assert colors[0].name == "red"
    assert colors[0].tier == "primary"
    assert all(c.name not in ("green", "lime", "forest green") for c in colors)


async def test_extract_colors_two_tone_tiers(tmp_path):
    png = _cutout_png(
        tmp_path / "hat.png", hat_color=(28, 37, 65), second_color=(245, 245, 245)
    )
    colors = extract_hat_colors(png)
    names = [c.name for c in colors]
    assert names[0] == "navy"  # dominant region
    assert "white" in names
    assert [c.tier for c in colors] == ["primary", "secondary", "tertiary"][: len(colors)]


async def test_extract_colors_requires_alpha_channel(tmp_path):
    """No mask (rembg failed, JPEG canonical) → no colors, never a guess."""
    jpg = tmp_path / "hat.jpg"
    Image.new("RGB", (100, 100), (200, 30, 30)).save(jpg, "JPEG")
    assert extract_hat_colors(jpg) == []


async def test_extract_colors_rejects_sliver_masks(tmp_path):
    """A nearly-empty mask (segmentation artifact) yields nothing."""
    img = Image.new("RGBA", (100, 100), (0, 255, 0, 0))
    for x in range(5):
        img.putpixel((x, 0), (200, 30, 30, 255))
    png = tmp_path / "sliver.png"
    img.save(png, "PNG")
    assert extract_hat_colors(png) == []


async def test_nearest_color_name_basics():
    assert nearest_color_name((28, 37, 65)) == "navy"
    assert nearest_color_name((250, 250, 250)) == "white"
    assert nearest_color_name((15, 15, 15)) == "black"


# ------------------------- google vision parsing ---------------------- #


async def test_detect_brand_logo_parses_top_logo(tmp_path, monkeypatch):
    png = _cutout_png(tmp_path / "hat.png")

    async def _fake_annotate(_payload, _key):
        return {
            "responses": [
                {
                    "logoAnnotations": [
                        {"description": "Melin", "score": 0.91},
                        {"description": "Nike", "score": 0.42},
                    ]
                }
            ]
        }

    monkeypatch.setattr("headroom.services.google_vision._annotate", _fake_annotate)
    result = await detect_brand_logo(png, "fake-key")
    assert result == ("Melin", 0.91)


async def test_detect_brand_logo_low_confidence_is_none(tmp_path, monkeypatch):
    png = _cutout_png(tmp_path / "hat.png")

    async def _fake_annotate(_payload, _key):
        return {"responses": [{"logoAnnotations": [{"description": "??", "score": 0.3}]}]}

    monkeypatch.setattr("headroom.services.google_vision._annotate", _fake_annotate)
    assert await detect_brand_logo(png, "fake-key") is None


async def test_detect_brand_logo_api_error_raises(tmp_path, monkeypatch):
    png = _cutout_png(tmp_path / "hat.png")

    async def _fake_annotate(_payload, _key):
        return {"responses": [{"error": {"message": "API key not valid"}}]}

    monkeypatch.setattr("headroom.services.google_vision._annotate", _fake_annotate)
    with pytest.raises(GoogleVisionError, match="API key not valid"):
        await detect_brand_logo(png, "bad-key")


# ------------------------- pipeline integration ----------------------- #


@pytest.fixture
def real_cutout(monkeypatch):
    """Replace the conftest rembg stub with one producing a real RGBA cutout,
    so the pipeline sees a PNG canonical photo with an honest alpha mask."""

    async def _fake_remove(input_path, output_path):
        final = output_path.with_suffix(".png")
        _cutout_png(final, hat_color=(28, 37, 65))
        return final

    monkeypatch.setattr(
        "headroom.services.hat_analysis_pipeline.remove_background", _fake_remove
    )


@pytest.fixture
def google_key(monkeypatch):
    async def _fake_get_key(_db):
        return "gv-test-key", "database"

    monkeypatch.setattr(
        "headroom.services.settings_service.get_google_vision_key", _fake_get_key
    )

    async def _fake_annotate(_payload, _key):
        return {
            "responses": [{"logoAnnotations": [{"description": "Melin", "score": 0.9}]}]
        }

    monkeypatch.setattr("headroom.services.google_vision._annotate", _fake_annotate)


async def _create_hat_with_photo(client):
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
    return hat_id, resp.json()


async def test_no_keys_no_mask_stays_skipped(client):
    """Default test env: no keys, rembg stubbed to None → exact old behavior."""
    _hat_id, data = await _create_hat_with_photo(client)
    assert data["analysis_status"] == "skipped"
    assert data["colors"] == []
    assert data["brand"] is None


async def test_fallback_colors_only_without_google_key(client, real_cutout):
    """Mask colors work with ZERO keys configured; brand stays empty."""
    _hat_id, data = await _create_hat_with_photo(client)
    assert data["analysis_status"] == "fallback"
    assert data["brand"] is None
    assert data["colors"], "mask-derived colors expected"
    assert data["colors"][0]["color_name"] == "navy"
    assert data["colors"][0]["tier"] == "primary"
    assert "fallback" in data["analysis_error"]


async def test_fallback_colors_and_brand_with_google_key(client, real_cutout, google_key):
    _hat_id, data = await _create_hat_with_photo(client)
    assert data["analysis_status"] == "fallback"
    assert data["brand"] == "Melin"
    assert data["colors"][0]["color_name"] == "navy"
    # Fallback must never invent Claude-only fields
    assert data["model_name"] is None
    assert data["estimated_new_price"] is None


async def test_claude_error_falls_back(client, real_cutout, google_key, monkeypatch):
    """Claude configured but failing → fallback catches instead of bare error."""
    from headroom.services.claude_analysis import ClaudeAnalysisError

    async def _fake_get_key(_db):
        return "sk-ant-fixture", "database"

    async def _boom(_path, _key, model=None, selected_style=None):  # noqa: ARG001
        raise ClaudeAnalysisError("rate limited")

    monkeypatch.setattr(
        "headroom.services.settings_service.get_anthropic_key", _fake_get_key
    )
    monkeypatch.setattr(
        "headroom.services.hat_analysis_pipeline.analyze_hat_image", _boom
    )

    _hat_id, data = await _create_hat_with_photo(client)
    assert data["analysis_status"] == "fallback"
    assert "rate limited" in data["analysis_error"]
    assert data["brand"] == "Melin"
    assert data["colors"]


async def test_reanalyze_without_key_runs_fallback(client, real_cutout, google_key):
    hat_id, _data = await _create_hat_with_photo(client)
    resp = await client.post(f"/api/hats/{hat_id}/reanalyze")
    assert resp.status_code == 200
    data = resp.json()
    assert data["analysis_status"] == "fallback"
    assert data["brand"] == "Melin"


async def test_reanalyze_without_key_or_fallback_still_400s(client):
    """No keys, no mask → reanalyze keeps the explicit 400."""
    hat_id, _data = await _create_hat_with_photo(client)
    resp = await client.post(f"/api/hats/{hat_id}/reanalyze")
    assert resp.status_code == 400


# ------------------------- settings routes ---------------------------- #


async def test_google_vision_key_roundtrip(client):
    resp = await client.get("/api/settings/google-vision-key")
    assert resp.json()["configured"] is False

    resp = await client.put(
        "/api/settings/google-vision-key", json={"api_key": "AIzaSy-test-1234567890"}
    )
    data = resp.json()
    assert data["configured"] is True
    assert data["source"] == "database"
    assert "AIzaSy-test-1234567890" not in (data["masked"] or "")

    resp = await client.delete("/api/settings/google-vision-key")
    assert resp.status_code == 204
    resp = await client.get("/api/settings/google-vision-key")
    assert resp.json()["configured"] is False
