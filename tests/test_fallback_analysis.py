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
        "headroom.services.background_removal.remove_background", _fake_remove
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

    async def _boom(_path, _key, model=None, selected_style=None, **_kw):
        raise ClaudeAnalysisError("rate limited")

    monkeypatch.setattr(
        "headroom.services.settings_service.get_anthropic_key", _fake_get_key
    )
    monkeypatch.setattr(
        "headroom.services.claude_analysis.analyze_hat_image", _boom
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


async def test_the_fallback_message_does_not_tell_you_to_add_a_key_you_have():
    """The advice has to match the reason.

    A real incident: the Anthropic ACCOUNT ran out of credit. The key was
    present, valid and had been working minutes earlier — but the message
    appended "Add a Claude API key" unconditionally, so all 235 hats told
    their owner to add the key they already had. It went unnoticed for three
    days, because the banner was the only thing visible and the true reason
    sat in a field the fallback branch never rendered.
    """
    from headroom.services.hat_analysis_pipeline import NO_ANTHROPIC_KEY, fallback_message

    billing = (
        "Claude analysis failed: Anthropic API error: Error code: 400 - "
        "Your credit balance is too low to access the Anthropic API."
    )

    # Whether the key is missing is STATED by the caller that found it
    # missing, never read out of the reason's wording — a reason that merely
    # mentions a key ("not configured", "invalid key") must not flip it.
    cases = [
        (billing, False, False),
        ("Claude analysis failed: Connection timed out", False, False),
        ("Claude analysis failed: Invalid Anthropic API key. not configured", False, False),
        (NO_ANTHROPIC_KEY, True, True),
    ]
    for reason, missing_key, should_mention_key in cases:
        message = fallback_message(
            reason, ["colors from photo cutout"], missing_key=missing_key
        )

        assert reason in message, "the real cause must survive into the message"
        mentions_key = "add a claude api key" in message.lower()
        assert mentions_key is should_mention_key, (
            f"reason {reason!r} produced advice {message!r}"
        )


async def test_a_keyless_upload_is_told_to_add_a_key(client, real_cutout):
    """Driven by the pipeline's REAL no-key reason, not a synthetic one.

    The advice used to be chosen by searching the reason for "not
    configured", "no api key" or "no anthropic key" — and the reason the
    pipeline actually writes, "No Anthropic API key configured", contains
    none of them. Every keyless install got "Reanalyze once the cause above
    is resolved" and was never pointed at Settings. The earlier test above
    only ever fed the function strings the pipeline never produces.
    """
    _hat_id, data = await _create_hat_with_photo(client)

    assert data["analysis_status"] == "fallback"
    assert "No Anthropic API key configured" in data["analysis_error"]
    assert "Add a Claude API key in Settings" in data["analysis_error"], data["analysis_error"]


async def test_a_keyless_reanalysis_is_told_to_add_a_key_too(client, real_cutout):
    """Same advice on the re-analysis entry point, which had its own copy of
    the no-key branch until the two were made one."""
    hat_id, _data = await _create_hat_with_photo(client)

    resp = await client.post(f"/api/hats/{hat_id}/reanalyze")

    assert resp.status_code == 200
    assert "Add a Claude API key in Settings" in resp.json()["analysis_error"]


# ------------------- the fallback spec's own rules --------------------- #
#
# Each rule below is stated in the fallback design (colors from the alpha
# mask only, deduped by palette name, general_color filled, a 0.6 logo floor,
# colors + brand and nothing else) — and each could be deleted with the suite
# green until these existed.


def _banded_cutout(path, *, band_alpha: int):
    """Opaque red hat plus a LARGE green band at `band_alpha`.

    The band covers more pixels than the hat, so if extraction ever counted
    it, green would be the dominant color rather than a trace.
    """
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    for x in range(100):
        for y in range(100):
            if y < 30:
                img.putpixel((x, y), (200, 30, 30, 255))
            elif y < 80:
                img.putpixel((x, y), (40, 180, 60, band_alpha))
    img.save(path, "PNG")
    return path


async def test_feathered_edges_below_the_alpha_floor_are_not_hat(tmp_path):
    """rembg feathers its edges: those pixels blend hat and background, and
    the floor (alpha >= 200) is what keeps the background out of them. Every
    other fixture here is alpha 0 or 255, so the floor itself was untested."""
    colors = extract_hat_colors(_banded_cutout(tmp_path / "h.png", band_alpha=199))

    assert [c.name for c in colors] == ["red"]


async def test_pixels_at_the_alpha_floor_are_hat(tmp_path):
    """The other side of the boundary: 200 is in."""
    colors = extract_hat_colors(_banded_cutout(tmp_path / "h.png", band_alpha=200))

    assert colors[0].name == "green", "the floor is inclusive — alpha 200 is hat"


async def test_two_shades_with_one_palette_name_are_one_color(tmp_path):
    """Dedupe by nearest palette name: a navy crown and a slightly lighter
    navy panel are one color to anyone searching, not two swatches."""
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    for x in range(100):
        for y in range(100):
            if y < 40:
                img.putpixel((x, y), (28, 37, 65, 255))
            elif y < 80:
                img.putpixel((x, y), (34, 44, 74, 255))
            else:
                img.putpixel((x, y), (245, 245, 245, 255))
    png = tmp_path / "shades.png"
    img.save(png, "PNG")

    names = [c.name for c in extract_hat_colors(png)]

    assert names == ["navy", "white"]


async def test_fallback_colors_carry_a_general_color_and_are_searchable(client, real_cutout):
    """`general_color` is what the default color search reads. Blank on a
    fallback color, and every Basic-ID hat vanished from search by color."""
    hat_id, data = await _create_hat_with_photo(client)
    assert data["analysis_status"] == "fallback"
    assert [c["general_color"] for c in data["colors"]] == ["navy"]

    resp = await client.get("/api/search", params={"q": "navy"})

    assert resp.status_code == 200
    assert hat_id in [h["id"] for h in resp.json()]


async def _logo_scored(tmp_path, monkeypatch, score):
    png = _cutout_png(tmp_path / "hat.png")

    async def _fake_annotate(_payload, _key):
        return {"responses": [{"logoAnnotations": [{"description": "Melin", "score": score}]}]}

    monkeypatch.setattr("headroom.services.google_vision._annotate", _fake_annotate)
    return await detect_brand_logo(png, "fake-key")


async def test_a_logo_just_under_the_floor_is_discarded(tmp_path, monkeypatch):
    assert await _logo_scored(tmp_path, monkeypatch, 0.59) is None


async def test_a_logo_at_the_floor_is_kept(tmp_path, monkeypatch):
    assert await _logo_scored(tmp_path, monkeypatch, 0.6) == ("Melin", 0.6)


def _category_listings(n=5, cents=6000):
    return [
        {"attributes": {
            "title": "A-Game Hydro - Black",
            "price": {"amount": cents},
            "publicData": {
                "condition": "new_without_tags", "size": "classic",
                "shopifyProductName": "A-Game Hydro - Black",
            },
        }}
        for _ in range(n)
    ]


async def test_the_fallback_never_prices_a_logo_identified_hat(
    client, real_cutout, google_key, monkeypatch
):
    """Colors + brand, and NO price — the fallback design's scope.

    With Vision reporting Melin, the fallback used to run the live resale
    lookup too: the hat, known only by its logo, got the median of its whole
    style category, and with no retail estimate that median became its
    valuation. The marketplace here WOULD answer with a price; the fallback
    must not ask.
    """
    calls = {"n": 0}

    async def _listings(_params):
        calls["n"] += 1
        return _category_listings()

    monkeypatch.setattr("headroom.services.melin_recap.query_listings", _listings)

    _hat_id, data = await _create_hat_with_photo(client)

    assert data["analysis_status"] == "fallback"
    assert data["brand"] == "Melin"
    assert data["resale_price"] is None
    assert data["resale_price_scope"] is None
    assert calls["n"] == 0, "the fallback consulted the marketplace"
    # The deep link is not a price, and it is still offered.
    assert "melinrecap.com" in (data["resale_price_url"] or "")
    assert data["resale_price_source"] == "Melin Recap"


async def test_the_fallback_leaves_a_price_it_did_not_write_alone(tmp_path, google_key):
    """No price written, and none erased: a hat whose earlier full analysis
    priced it keeps that price when a later run can only fall back."""
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import run_fallback_analysis

    hat = Hat(style="a_game", condition="new", size="classic")
    hat.resale_price = 85.0
    hat.resale_price_scope = "model"
    hat.resale_price_source = "Melin Recap · median of 4 live A-Game Hydro listings"
    png = _cutout_png(tmp_path / "hat.png", hat_color=(28, 37, 65))

    applied = await run_fallback_analysis(None, hat, png, reason="Claude analysis failed: x")

    assert applied is True
    assert hat.brand == "Melin"
    assert (hat.resale_price, hat.resale_price_scope) == (85.0, "model")
    assert hat.resale_price_source.startswith("Melin Recap · median of 4")
    assert "melinrecap.com" in hat.resale_price_url


# ------------------ the fallback never raises --------------------------- #


class _VisionResp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _vision_http(monkeypatch, resp):
    """Stub the transport under the REAL `_annotate`, so its own decoding runs."""
    from headroom.services import google_vision

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, *_a, **_kw):
            return resp

    monkeypatch.setattr(google_vision.httpx, "AsyncClient", lambda **_kw: _Client())


@pytest.fixture
def vision_key(monkeypatch):
    async def _fake_get_key(_db):
        return "gv-test-key", "database"

    monkeypatch.setattr(
        "headroom.services.settings_service.get_google_vision_key", _fake_get_key
    )


@pytest.mark.parametrize(
    "resp",
    [
        # A captive portal or proxy answering 200 with a page.
        _VisionResp(200, ValueError("Expecting value: line 1 column 1 (char 0)"), "<html>"),
        # JSON, but not the documented object.
        _VisionResp(200, ["not", "an", "object"]),
        _VisionResp(200, {"responses": "nope"}),
        _VisionResp(200, {"responses": [{"logoAnnotations": {"description": "Melin"}}]}),
        # Right shape, wrong types: a string score must not reach `>=`.
        _VisionResp(200, {"responses": [{"logoAnnotations": [{"description": "Melin", "score": "0.9"}]}]}),
        _VisionResp(200, {"responses": [{"error": "quota exhausted"}]}),
    ],
    ids=["html-200", "json-list", "responses-not-list", "annotations-not-list",
         "string-score", "error-not-object"],
)
async def test_a_malformed_vision_reply_costs_the_brand_not_the_colors(
    tmp_path, monkeypatch, vision_key, resp
):
    """Each of these used to raise a raw decode, type or attribute error out
    of the fallback — throwing away mask colors already extracted, and in a
    bulk import deleting the hat."""
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import run_fallback_analysis

    _vision_http(monkeypatch, resp)
    hat = Hat(style="a_game", condition="new", size="classic")
    png = _cutout_png(tmp_path / "hat.png", hat_color=(28, 37, 65))

    applied = await run_fallback_analysis(None, hat, png, reason="no claude")

    assert applied is True
    assert hat.analysis_status == "fallback"
    assert [c.color_name for c in hat.colors] == ["navy"]
    assert hat.brand is None


@pytest.mark.parametrize(
    "resp",
    [
        _VisionResp(200, ValueError("Expecting value"), "<html>"),
        _VisionResp(200, ["not", "an", "object"]),
        _VisionResp(200, {"responses": "nope"}),
        _VisionResp(200, {"responses": [{"logoAnnotations": {"description": "Melin"}}]}),
        _VisionResp(200, {"responses": [{"error": "quota exhausted"}]}),
    ],
    ids=["html-200", "json-list", "responses-not-list", "annotations-not-list",
         "error-not-object"],
)
async def test_a_malformed_vision_reply_is_the_modules_own_error(tmp_path, monkeypatch, resp):
    """At the seam itself, not only through the pipeline's backstop: every
    malformed reply is `GoogleVisionError`, the one type callers catch."""
    _vision_http(monkeypatch, resp)
    png = _cutout_png(tmp_path / "hat.png")

    with pytest.raises(GoogleVisionError):
        await detect_brand_logo(png, "key")


async def test_a_malformed_logo_entry_is_skipped_not_fatal(tmp_path, monkeypatch):
    """One bad annotation beside a good one must not cost the good one."""
    _vision_http(monkeypatch, _VisionResp(200, {"responses": [{"logoAnnotations": [
        "garbage",
        {"description": "Melin", "score": "0.99"},
        {"description": "", "score": 0.97},
        {"description": "Melin", "score": 0.9},
    ]}]}))
    png = _cutout_png(tmp_path / "hat.png")

    assert await detect_brand_logo(png, "key") == ("Melin", 0.9)


async def test_a_vision_key_no_header_can_carry_is_a_vision_error():
    """A key pasted with a zero-width space looks fine in the Settings field;
    httpx refuses it as a header value before anything is sent."""
    from headroom.services import google_vision

    with pytest.raises(GoogleVisionError, match="re-enter it"):
        await google_vision._annotate({}, "AIza\u200bSy-key")


async def test_an_expected_vision_failure_is_logged_quietly(
    tmp_path, monkeypatch, vision_key, caplog
):
    """`GoogleVisionError` is the expected degrade — INFO, no traceback. The
    backstop's ERROR-with-traceback is for failures nobody has named."""
    from headroom.models.hat import Hat
    from headroom.services import hat_analysis_pipeline

    async def _vision_down(_path, _key):
        raise GoogleVisionError("Vision API 503: backend error")

    monkeypatch.setattr("headroom.services.google_vision.detect_brand_logo", _vision_down)
    caplog.set_level("INFO")
    hat = Hat(style="a_game", condition="new", size="classic")
    png = _cutout_png(tmp_path / "hat.png", hat_color=(28, 37, 65))

    assert await hat_analysis_pipeline.run_fallback_analysis(None, hat, png, reason="r") is True
    assert hat.colors
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("503" in r.getMessage() for r in caplog.records)


async def test_an_unnamed_vision_failure_is_contained_and_logged_loudly(
    tmp_path, monkeypatch, vision_key, caplog
):
    """The backstop: whatever else goes wrong in logo detection, the colors
    survive and the failure is logged with its traceback."""
    from headroom.models.hat import Hat
    from headroom.services import hat_analysis_pipeline

    async def _bug(_path, _key):
        raise RuntimeError("something nobody anticipated")

    monkeypatch.setattr("headroom.services.google_vision.detect_brand_logo", _bug)
    caplog.set_level("INFO")
    hat = Hat(style="a_game", condition="new", size="classic")
    png = _cutout_png(tmp_path / "hat.png", hat_color=(28, 37, 65))

    assert await hat_analysis_pipeline.run_fallback_analysis(None, hat, png, reason="r") is True
    assert [c.color_name for c in hat.colors] == ["navy"]
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert errors and errors[0].exc_info, "an unnamed failure must carry its traceback"


async def test_a_color_extraction_failure_still_keeps_the_brand(
    tmp_path, monkeypatch, google_key
):
    """The other half of "each step can fail without breaking the others"."""
    from headroom.models.hat import Hat
    from headroom.services import hat_analysis_pipeline

    def _broken(_path):
        raise RuntimeError("decoder exploded")

    monkeypatch.setattr("headroom.services.color_extraction.extract_hat_colors", _broken)
    hat = Hat(style="a_game", condition="new", size="classic")
    png = _cutout_png(tmp_path / "hat.png")

    applied = await hat_analysis_pipeline.run_fallback_analysis(None, hat, png, reason="r")

    assert applied is True
    assert hat.brand == "Melin"
    assert list(hat.colors) == []


# ------------------ colors the owner set survive re-analysis ----------------- #

_FOREST = [{"color_name": "Forest Green", "general_color": "green",
            "hex_value": "#1e5532", "tier": "primary"}]


async def test_colors_the_owner_set_survive_a_keyless_reanalysis(client, real_cutout):
    """Correcting "gray" to "forest green" and tapping Reanalyze gave the
    analyzer's gray back, with nothing saying why."""
    hat_id, _data = await _create_hat_with_photo(client)
    put = (await client.put(f"/api/hats/{hat_id}/colors", json={"colors": _FOREST})).json()
    assert put["colors_source"] == "owner"

    resp = await client.post(f"/api/hats/{hat_id}/reanalyze")

    # The owner's palette is not "colors obtained", and with no Vision key
    # there is no brand either: the fallback produced nothing, so it says so.
    assert resp.status_code == 400
    after = (await client.get(f"/api/hats/{hat_id}")).json()
    assert [c["color_name"] for c in after["colors"]] == ["Forest Green"]


async def test_clearing_the_owners_colors_hands_them_back_to_analysis(client, real_cutout):
    hat_id, _data = await _create_hat_with_photo(client)
    await client.put(f"/api/hats/{hat_id}/colors", json={"colors": _FOREST})
    cleared = (await client.put(f"/api/hats/{hat_id}/colors", json={"colors": []})).json()
    assert cleared["colors_source"] is None

    resp = await client.post(f"/api/hats/{hat_id}/reanalyze")

    assert resp.status_code == 200, resp.text
    assert [c["color_name"] for c in resp.json()["colors"]] == ["navy"]


async def test_a_full_reanalysis_updates_the_hat_but_keeps_the_owners_colors(
    client, real_cutout, monkeypatch
):
    """The Claude path goes through the same gate: its answer still lands,
    the owner's palette still stands."""
    from headroom.services.claude_analysis import AnalyzedColor, HatAnalysis

    hat_id, _data = await _create_hat_with_photo(client)
    await client.put(f"/api/hats/{hat_id}/colors", json={"colors": _FOREST})

    async def _key(_db):
        return "sk-ant-fixture", "database"

    async def _analyze(*_a, **_kw):
        return HatAnalysis(
            brand="Melin", model_name="A-Game", model_confidence="high",
            style_descriptor="snapback", design_notes="n", estimated_new_price_usd=None,
            colors=[AnalyzedColor(name="gray", hex="#808080", tier="primary")],
        )

    monkeypatch.setattr("headroom.services.settings_service.get_anthropic_key", _key)
    monkeypatch.setattr("headroom.services.claude_analysis.analyze_hat_image", _analyze)

    body = (await client.post(f"/api/hats/{hat_id}/reanalyze")).json()

    assert body["model_name"] == "A-Game"
    assert [c["color_name"] for c in body["colors"]] == ["Forest Green"]


async def test_analysis_colors_obey_the_rules_an_edit_does(tmp_path):
    """Every stored color round-trips through `ColorTagWrite`: an over-long
    analyzer name is trimmed to the column, and a color the wire type refuses
    is dropped rather than stored (or allowed to fail the analysis)."""
    from headroom.models.hat import Hat
    from headroom.schemas.hat import ColorTagWrite
    from headroom.services import hat_service

    long_name = "a remarkably specific heathered charcoal with blue undertones and flecks"
    tags = [
        hat_service.analysis_color(long_name, "#333A44", "primary"),
        hat_service.analysis_color("mystery", "not-a-hex", "primary"),
        hat_service.analysis_color("accent red", "#cc0000", "sparkle"),
    ]
    assert tags[1] is None and tags[2] is None

    hat = Hat(style="a_game", condition="new", size="classic")
    assert hat_service.replace_analysis_colors(hat, [t for t in tags if t]) is True

    [row] = hat.colors
    assert len(row.color_name) == 50
    assert row.hex_value == "#333a44"
    ColorTagWrite(
        color_name=row.color_name, general_color=row.general_color,
        hex_value=row.hex_value, tier=row.tier,
    )
