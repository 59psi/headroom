"""Cutout fidelity: hats must keep their bills and stay opaque.

Two defects produced the same visible symptom — hats rendering faded and
brim-less on the near-black canvas — from opposite ends of the pipeline:

1. Soft, mid-confidence alpha from the saliency model came through as
   semi-transparent pixels ("ghosted"). `post_process_mask` binarises it.
2. Re-analysis re-ran background removal against the stored PNG cutout,
   writing the result back over the same file, so every Reanalyze ate a
   little more of the alpha and the bill.
"""

from __future__ import annotations

import sys
import types

import pytest
from PIL import Image

from headroom.services import background_removal


@pytest.mark.anyio
async def test_background_removal_binarises_the_mask(monkeypatch, tmp_path):
    """`post_process_mask=True` must reach rembg, or cutouts render ghosted.

    Nothing else catches this: dropping the kwarg still produces a valid PNG,
    just a semi-transparent one, so every other test stays green while hats
    look washed out in the browser.
    """
    captured: dict = {}

    def _fake_remove(src, session=None, **kwargs):
        captured.update(kwargs)
        return Image.new("RGBA", (8, 8), (200, 30, 90, 255))

    fake_rembg = types.ModuleType("rembg")
    fake_rembg.remove = _fake_remove
    fake_rembg.new_session = lambda *_a, **_k: "session"
    monkeypatch.setitem(sys.modules, "rembg", fake_rembg)
    monkeypatch.setattr(background_removal, "_get_session", lambda: "session")

    src = tmp_path / "hat.jpg"
    Image.new("RGB", (8, 8), (10, 10, 10)).save(src, "JPEG")

    out = background_removal._remove_sync(src, tmp_path / "hat")

    assert out.exists()
    assert captured.get("post_process_mask") is True, (
        "post_process_mask must be enabled — without it the soft alpha band "
        "renders as a ghosted, semi-transparent hat"
    )


@pytest.mark.anyio
async def test_reanalysis_does_not_re_cut_an_existing_cutout(
    monkeypatch, tmp_path, db_session
):
    """A .png input is already a cutout — running rembg on it destroys it.

    `remove_background`'s output path is the input stem + ".png", so for a
    stored cutout the output IS the input: rembg would re-segment an already
    transparent image and overwrite the only copy, fading the hat and trimming
    the bill a bit more each pass.
    """
    from headroom.models.hat import Hat
    from headroom.services import hat_analysis_pipeline

    calls: list = []

    async def _spy(input_path, output_path):
        calls.append(input_path)
        return None

    monkeypatch.setattr(hat_analysis_pipeline, "remove_background", _spy)

    async def _no_key(_db):
        return "", None

    monkeypatch.setattr(
        "headroom.services.settings_service.get_anthropic_key", _no_key
    )

    png = tmp_path / "hat-abc.png"
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(png, "PNG")
    hat = Hat(condition="new", size="classic", style="a_game")

    await hat_analysis_pipeline.finalize_hat_photo(db_session, hat, png)

    assert calls == [], "background removal must not run against a stored cutout"
    assert hat.photo_path == "hats/hat-abc.png"
    assert png.exists()


@pytest.mark.anyio
async def test_a_fresh_jpeg_upload_still_gets_background_removed(
    monkeypatch, tmp_path, db_session
):
    """The guard must not disable the upload path it shares."""
    from headroom.models.hat import Hat
    from headroom.services import hat_analysis_pipeline

    calls: list = []

    async def _spy(input_path, output_path):
        calls.append(input_path)
        return None

    monkeypatch.setattr(hat_analysis_pipeline, "remove_background", _spy)

    async def _no_key(_db):
        return "", None

    monkeypatch.setattr(
        "headroom.services.settings_service.get_anthropic_key", _no_key
    )

    jpg = tmp_path / "hat-xyz.jpg"
    Image.new("RGB", (8, 8), (10, 10, 10)).save(jpg, "JPEG")
    hat = Hat(condition="new", size="classic", style="a_game")

    await hat_analysis_pipeline.finalize_hat_photo(db_session, hat, jpg)

    assert calls == [jpg], "a fresh JPEG upload must still be cut out"

