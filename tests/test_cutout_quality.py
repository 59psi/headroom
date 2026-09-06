"""Cutout fidelity: hats must keep their bills and stay opaque.

Two defects produced the same visible symptom — hats rendering faded and
brim-less on the near-black canvas — from opposite ends of the pipeline:

1. Soft, mid-confidence alpha from the saliency model came through as
   semi-transparent pixels ("ghosted"). `_harden_alpha` ramps it toward
   opaque — a binarizing `post_process_mask` was tried first and replaced,
   see the test docstrings below.
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
async def test_alpha_ramp_keeps_a_low_confidence_brim_and_still_kills_the_haze():
    """The hat's bill is where a saliency model is least confident.

    2.6.2 hardened the mask with rembg's `post_process_mask`, which blurs then
    thresholds at 127 — that removed the ghosting but *deleted* every pixel the
    model was under ~50% sure about, i.e. exactly the bill. This pins the ramp
    that replaced it: low-confidence structure survives AND becomes opaque,
    while genuine background still goes away.
    """
    import numpy as np

    from headroom.services.background_removal import _harden_alpha

    def alpha_at(value: int) -> int:
        img = Image.new("RGBA", (4, 4), (200, 30, 90, value))
        return np.asarray(_harden_alpha(img).getchannel("A"))[0, 0]

    # A brim the model was only ~39% sure about must not be thrown away, and
    # must not render as a see-through smear either.
    assert alpha_at(100) > 150, "a low-confidence brim was erased or left ghosted"
    # Confident pixels are fully opaque — no haze over the hat body.
    assert alpha_at(200) == 255
    assert alpha_at(128) == 255
    # Genuine background still disappears.
    assert alpha_at(10) == 0
    assert alpha_at(0) == 0


@pytest.mark.anyio
async def test_background_removal_hardens_the_alpha_it_writes(monkeypatch, tmp_path):
    """`_remove_sync` must actually apply the ramp, not just define it."""
    import numpy as np

    fake_rembg = types.ModuleType("rembg")
    # A soft mask, as a saliency model would emit around a thin edge.
    fake_rembg.remove = lambda src, session=None, **kw: Image.new(
        "RGBA", (8, 8), (200, 30, 90, 100)
    )
    fake_rembg.new_session = lambda *_a, **_k: "session"
    monkeypatch.setitem(sys.modules, "rembg", fake_rembg)
    monkeypatch.setattr(background_removal, "_get_session", lambda: "session")

    src = tmp_path / "hat.jpg"
    Image.new("RGB", (8, 8), (10, 10, 10)).save(src, "JPEG")

    out = background_removal._remove_sync(src, tmp_path / "hat")

    written = np.asarray(Image.open(out).getchannel("A"))
    assert written[0, 0] > 150, (
        "the saved cutout still carries the model's raw soft alpha — hats will "
        "render washed out"
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

