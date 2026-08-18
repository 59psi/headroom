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
import math
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


def palette() -> list[dict]:
    """The curated palette as [{name, hex}] — served to the UI as filter chips."""
    return [
        {"name": name, "hex": "#{:02x}{:02x}{:02x}".format(*rgb)}
        for name, rgb in _PALETTE
    ]


def parse_hex(value: str) -> tuple[int, int, int] | None:
    """'#1c2541' / '1c2541' → (28, 37, 65); None when malformed."""
    v = value.strip().lstrip("#")
    if len(v) != 6:
        return None
    try:
        return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))
    except ValueError:
        return None


def normalize_hex_name(hex_value: str | None, fallback: str) -> str:
    """Palette name for a hex color; `fallback` when the hex is unusable.

    Used to normalize free-text color names (Claude says "sky blue",
    "powder blue", …) onto the fixed palette vocabulary so color filters
    behave consistently.
    """
    rgb = parse_hex(hex_value) if hex_value else None
    return nearest_color_name(rgb) if rgb else fallback


_PALETTE_NAMES: dict[str, str] = {name.lower(): name for name, _rgb in _PALETTE}


def normalize_color_name(name: str) -> str:
    """Snap a hand-typed colour name onto the palette's spelling.

    The counterpart to `normalize_hex_name` for the case where a human, not the
    analyser, supplied the name. Matching by NAME rather than by hex is the
    whole point: a person correcting a mis-detected colour is telling us the
    stored hex is wrong, so re-deriving from that hex would just reinstate the
    error. Anything not in the palette passes through trimmed and unchanged —
    the user's word beats our vocabulary.
    """
    cleaned = (name or "").strip()
    return _PALETTE_NAMES.get(cleaned.lower(), cleaned)


# --------------------- perceptual color distance ---------------------- #
# sRGB → CIELAB, pure Python (D65), then CIEDE2000 for the distance.
#
# LAB was designed so that plain Euclidean distance (ΔE*76) would be
# perceptually uniform, and it isn't — the error is worst in exactly the
# region this collection lives in. Saturated blues and navies are pushed far
# apart in a*b* while looking near-identical, so a navy search returned a
# spread of blues ranked in an order that didn't match what you see, and
# two navies a person would call the same shade scored further apart than a
# navy and a slate grey.
#
# CIEDE2000 is the current CIE standard and fixes that with weighting terms
# for lightness, chroma and hue plus a rotation term for the blue region.
# It's more arithmetic but it is all local — no dependency, no lookup tables
# — and it runs (hats x swatches) times over a collection of hundreds, which
# is nothing.


def _srgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def _lin(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (_lin(c) for c in rgb)
    # sRGB D65 → XYZ
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def _f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    fx, fy, fz = _f(x), _f(y), _f(z)
    return (116 * fy) - 16, 500 * (fx - fy), 200 * (fy - fz)


def lab_of(hex_value: str) -> tuple[float, float, float] | None:
    """Hex → CIE L*a*b*, or None if it doesn't parse.

    Exposed so a caller comparing ONE colour against many can convert it once.
    `_srgb_to_lab` runs three `** 2.4` powers per channel, and the colour search
    was paying that for the search target on every stored swatch it looked at.
    """
    rgb = parse_hex(hex_value)
    return None if rgb is None else _srgb_to_lab(rgb)


def lab_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """CIEDE2000 between two already-converted LAB triples.

    Transcribed from the CIE standard as restated in Sharma, Wu & Dalal
    (2005), whose paper also supplies the 34-pair test set this is checked
    against in `tests/test_find_the_hat.py` — the formula has several places
    (the hue-average discontinuity, the `atan2` quadrant, degrees vs radians)
    where a plausible-looking mistake still returns plausible-looking numbers,
    so it is pinned to reference values rather than eyeballed.

    Named `lab_distance` still, because every caller wants "the perceptual
    distance" and none of them should have to care which formula that is.
    """
    l1, a1, b1 = a
    l2, a2, b2 = b

    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0

    # G expands a* in low-chroma colours so near-greys don't get a hue that
    # swamps the comparison.
    c_bar7 = c_bar ** 7
    g = 0.5 * (1.0 - math.sqrt(c_bar7 / (c_bar7 + 25.0 ** 7)))
    a1p = (1.0 + g) * a1
    a2p = (1.0 + g) * a2

    c1p = math.hypot(a1p, b1)
    c2p = math.hypot(a2p, b2)

    def _hue(ap: float, bp: float) -> float:
        if ap == 0.0 and bp == 0.0:
            return 0.0
        return math.degrees(math.atan2(bp, ap)) % 360.0

    h1p = _hue(a1p, b1)
    h2p = _hue(a2p, b2)

    dlp = l2 - l1
    dcp = c2p - c1p

    # Hue difference takes the short way round the circle; undefined (and so
    # zero) when either colour is achromatic.
    if c1p * c2p == 0.0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180.0:
        dhp = h2p - h1p
    elif h2p - h1p > 180.0:
        dhp = h2p - h1p - 360.0
    else:
        dhp = h2p - h1p + 360.0
    dHp = 2.0 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp) / 2.0)

    l_bar_p = (l1 + l2) / 2.0
    c_bar_p = (c1p + c2p) / 2.0

    # Mean hue has a discontinuity at the 0/360 wrap that a naive average
    # gets wrong by 180 degrees.
    if c1p * c2p == 0.0:
        h_bar_p = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        h_bar_p = (h1p + h2p) / 2.0
    elif h1p + h2p < 360.0:
        h_bar_p = (h1p + h2p + 360.0) / 2.0
    else:
        h_bar_p = (h1p + h2p - 360.0) / 2.0

    t = (
        1.0
        - 0.17 * math.cos(math.radians(h_bar_p - 30.0))
        + 0.24 * math.cos(math.radians(2.0 * h_bar_p))
        + 0.32 * math.cos(math.radians(3.0 * h_bar_p + 6.0))
        - 0.20 * math.cos(math.radians(4.0 * h_bar_p - 63.0))
    )

    d_theta = 30.0 * math.exp(-(((h_bar_p - 275.0) / 25.0) ** 2))
    c_bar_p7 = c_bar_p ** 7
    r_c = 2.0 * math.sqrt(c_bar_p7 / (c_bar_p7 + 25.0 ** 7))
    # The blue-region rotation — the term that makes navies behave.
    r_t = -math.sin(math.radians(2.0 * d_theta)) * r_c

    s_l = 1.0 + (0.015 * (l_bar_p - 50.0) ** 2) / math.sqrt(20.0 + (l_bar_p - 50.0) ** 2)
    s_c = 1.0 + 0.045 * c_bar_p
    s_h = 1.0 + 0.015 * c_bar_p * t

    # kL = kC = kH = 1: the reference conditions, and there is nothing about
    # a phone screen showing hat photos that justifies a graphic-arts tweak.
    term_l = dlp / s_l
    term_c = dcp / s_c
    term_h = dHp / s_h
    return math.sqrt(
        term_l ** 2 + term_c ** 2 + term_h ** 2 + r_t * term_c * term_h
    )


def color_distance(hex_a: str, hex_b: str) -> float | None:
    """Perceptual distance (CIEDE2000) between two hex colors; None if unparsable."""
    a, b = lab_of(hex_a), lab_of(hex_b)
    if a is None or b is None:
        return None
    return lab_distance(a, b)


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
