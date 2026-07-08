"""Local dominant-color extraction from a background-removed hat photo.

Fallback color source when Claude Vision is unavailable. Background rejection
is exact by construction: rembg has already segmented the hat, so we read
colors ONLY from pixels the alpha mask marks as hat (alpha >= _ALPHA_MIN).
Images without an alpha channel (rembg failed, canonical photo is the JPEG)
yield no colors — we never guess from a background-contaminated frame.

Pillow-only, no network, no new dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

# Feathered rembg edges blend hat and background; a high floor keeps them out.
_ALPHA_MIN = 200
# Below this many opaque pixels the "hat" is likely a segmentation artifact.
_MIN_OPAQUE_PIXELS = 100
# Thumbnail bound: keeps quantize fast and the pixel strip under Pillow's
# per-side image size limit.
_MAX_SIDE = 128
_QUANTIZE_COLORS = 8
_TIERS = ("primary", "secondary", "tertiary")

# Curated palette for naming. Names double as `general_color`, so they should
# match what someone would type into search ("navy", "tan"), not CSS exotica.
_PALETTE: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("black", (18, 18, 18)),
    ("charcoal", (54, 60, 66)),
    ("gray", (128, 128, 128)),
    ("silver", (192, 192, 192)),
    ("white", (245, 245, 245)),
    ("cream", (250, 240, 215)),
    ("beige", (222, 205, 175)),
    ("tan", (188, 152, 106)),
    ("brown", (110, 74, 46)),
    ("dark brown", (66, 48, 32)),
    ("maroon", (110, 32, 42)),
    ("red", (200, 40, 40)),
    ("orange", (235, 125, 35)),
    ("gold", (212, 175, 55)),
    ("yellow", (240, 210, 60)),
    ("olive", (110, 110, 50)),
    ("lime", (150, 205, 60)),
    ("green", (55, 135, 70)),
    ("forest green", (30, 85, 50)),
    ("teal", (35, 128, 128)),
    ("light blue", (140, 185, 225)),
    ("blue", (50, 90, 190)),
    ("navy", (28, 37, 65)),
    ("purple", (115, 65, 160)),
    ("lavender", (185, 165, 215)),
    ("pink", (230, 130, 170)),
)


@dataclass(frozen=True)
class ExtractedColor:
    name: str
    hex: str
    tier: str


def nearest_color_name(rgb: tuple[int, int, int]) -> str:
    """Map an RGB triple to the closest curated palette name."""
    r, g, b = rgb
    return min(
        _PALETTE,
        key=lambda entry: (r - entry[1][0]) ** 2
        + (g - entry[1][1]) ** 2
        + (b - entry[1][2]) ** 2,
    )[0]


def extract_hat_colors(image_path: Path, max_colors: int = 3) -> list[ExtractedColor]:
    """Return up to `max_colors` dominant hat colors, ranked, background-free.

    Empty list when the image has no alpha channel or too few opaque pixels —
    callers treat that as "no fallback colors available", not an error.
    """
    with Image.open(image_path) as img:
        if img.mode != "RGBA":
            return []
        img.thumbnail((_MAX_SIDE, _MAX_SIDE))
        raw = img.tobytes()  # packed RGBA
    hat_pixels = [
        (raw[i], raw[i + 1], raw[i + 2])
        for i in range(0, len(raw), 4)
        if raw[i + 3] >= _ALPHA_MIN
    ]

    if len(hat_pixels) < _MIN_OPAQUE_PIXELS:
        return []

    # Median-cut quantize the hat-only pixel strip, then rank clusters by size.
    strip = Image.new("RGB", (len(hat_pixels), 1))
    strip.putdata(hat_pixels)
    quantized = strip.quantize(
        colors=min(_QUANTIZE_COLORS, len(hat_pixels)), method=Image.Quantize.MEDIANCUT
    )
    palette = quantized.getpalette()
    counts = sorted(quantized.getcolors(), reverse=True)  # [(count, palette_idx)]

    results: list[ExtractedColor] = []
    seen_names: set[str] = set()
    for count, idx in counts:
        if len(results) >= max_colors:
            break
        # Ignore clusters too small to be a deliberate design color.
        if count / len(hat_pixels) < 0.05:
            continue
        rgb = tuple(palette[idx * 3 : idx * 3 + 3])
        name = nearest_color_name(rgb)
        if name in seen_names:
            continue
        seen_names.add(name)
        results.append(
            ExtractedColor(
                name=name,
                hex="#{:02x}{:02x}{:02x}".format(*rgb),
                tier=_TIERS[len(results)],
            )
        )
    return results
