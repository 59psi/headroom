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
    """Snap a hand-typed color name onto the palette's spelling.

    The counterpart to `normalize_hex_name` for the case where a human, not the
    analyser, supplied the name. Matching by NAME rather than by hex is the
    whole point: a person correcting a mis-detected color is telling us the
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

    Exposed so a caller comparing ONE color against many can convert it once.
    `_srgb_to_lab` runs three `** 2.4` powers per channel, and the color search
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

    # G expands a* in low-chroma colors so near-greys don't get a hue that
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
    # zero) when either color is achromatic.
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


# ------------------------ grey is not a dark color -------------------- #
# Chroma is how much color a color has: 0 is a pure grey, ~60 a vivid
# purple. Below NEUTRAL there is no hue worth speaking of; at or above
# CHROMATIC there plainly is.
#
# These exist because distance alone cannot answer "is this hat purple?", and
# no amount of tuning a single threshold will make it. CIEDE2000 divides the
# chroma difference by S_C = 1 + 0.045 * C_bar, which is correct for the job
# it was designed for — judging whether two nearly-identical samples of a dye
# match — and wrong here. A mid grey and a saturated purple differ by 55 units
# of chroma; that divisor compresses the gap to ~22, and when their lightness
# happens to agree the pair scores ~17. So a grey hat sat NEARER the purple
# swatch than two genuinely different purples sit to each other, and every
# color search returned the whole shelf of black/charcoal/navy/grey caps.
#
# The test is a RATIO, not an absolute floor, because "how much color counts
# as some color" depends on the color. Teal is itself only C=27 where red is
# C=73, so a muted teal at C=10 has a real share of teal's chroma while a
# blue-grey at C=12 has almost none of purple's C=59. An absolute floor cannot
# see that difference: set low enough to keep the muted teal findable, it lets
# blue-grey match purple; set high enough to stop that, it throws away every
# dark teal and forest green in the collection. The ratio separates them —
# 0.39 for the teal, 0.20 for the blue-grey.
#
# CHROMATIC_CHROMA gates the whole rule: below it the target is itself muted
# enough that nothing is claimed, so white/cream and navy/charcoal are judged
# on distance like everything else.
CHROMATIC_CHROMA = 20.0
MIN_CHROMA_RATIO = 0.25


def chroma_of(lab: tuple[float, float, float]) -> float:
    """C* — distance from the neutral axis. 0 is grey, ~73 is a vivid red."""
    _l, a, b = lab
    return math.hypot(a, b)


def is_neutral_mismatch(
    lab_a: tuple[float, float, float], lab_b: tuple[float, float, float]
) -> bool:
    """True when one color has essentially none of the other's color.

    Deliberately NOT a penalty on the chroma difference in general. Navy and
    blue differ by 41 units of chroma, red and maroon by 36, and those pairs
    must keep matching — they are the dark and bright versions of one hue.
    What makes grey-vs-purple different is not the size of the gap but that
    one side has no hue at all, so there is nothing for the other to be a
    darker version OF. Hence a ratio: a muted teal keeps 39% of teal's chroma
    and stays a teal, while a blue-grey holds 20% of purple's and is a grey.
    """
    c_a, c_b = chroma_of(lab_a), chroma_of(lab_b)
    paler, bolder = min(c_a, c_b), max(c_a, c_b)
    if bolder < CHROMATIC_CHROMA:
        return False  # neither is emphatic enough to rule anything out
    return (paler / bolder) < MIN_CHROMA_RATIO


# ---- color identity, which is not color distance ---------------------- #
#
# Every curated palette name, grouped under the word a person would actually
# use for it. This is what color search matches on. It replaced a distance
# threshold, and the reason is a measurement rather than a preference.
#
# Within-family distances run up to **ΔE 55.8** — light blue to navy, which
# are both unarguably "blue". Cross-family distances go down to **15.4**,
# black to navy. The ranges do not merely overlap, they invert: no threshold
# anywhere can keep the first pair and reject the second. At the cutoff of 26
# this replaced, 51 cross-family pairs matched — black/navy, silver/beige,
# white/cream, charcoal/dark brown — which is why a search returned most of
# the shelf whatever color you asked for.
#
# Three releases were spent moving that number (30, then 22, then 26) and the
# file's own comment already had the answer: a distance threshold cannot
# answer "is this hat purple?", and tuning it will never make it. Distance
# measures how far apart two colors look. Search asks what a color IS.
# Those are different questions, and only the second one has a shelf of hats
# as its answer.
#
# So distance stops deciding membership and goes back to what it is good at:
# ORDERING the hats that are already the right color. The palette is curated
# and closed, so membership has an exact answer.
#
# The groups are the basic color words, not a hue wheel. Deliberately strict:
# "gold" does not return tans, "blue" does not return teals. Over-matching is
# the failure being fixed, and a neighbour that is genuinely wanted is one
# entry away — whereas a search that returns everything is not fixable by the
# person using it.
# A name may belong to more than one word. Charcoal is both a soft black and
# a dark grey, and someone searching either should find it — forcing it into
# one bucket makes the other search wrong.
_COLOR_FAMILIES: dict[str, frozenset[str]] = {
    "black": frozenset({"black"}), "charcoal": frozenset({"black", "gray"}),
    "gray": frozenset({"gray"}), "silver": frozenset({"gray", "white"}),
    "white": frozenset({"white"}),
    "cream": frozenset({"cream"}), "beige": frozenset({"cream", "brown"}),
    "tan": frozenset({"brown"}), "brown": frozenset({"brown"}),
    "dark brown": frozenset({"brown"}),
    "maroon": frozenset({"red"}), "red": frozenset({"red"}),
    "pink": frozenset({"pink"}),
    "orange": frozenset({"orange"}),
    "gold": frozenset({"yellow"}), "yellow": frozenset({"yellow"}),
    "olive": frozenset({"green"}), "lime": frozenset({"green"}),
    "green": frozenset({"green"}), "forest green": frozenset({"green"}),
    "teal": frozenset({"teal"}),
    "light blue": frozenset({"blue"}), "blue": frozenset({"blue"}),
    "navy": frozenset({"blue"}),
    "purple": frozenset({"purple"}), "lavender": frozenset({"purple"}),
}

#: How much further than the nearest palette entry another one may sit and
#: still describe the same swatch. A margin, not a distance cutoff: it asks
#: "is this classification ambiguous?", never "is this color close?".
#:
#: Saturated colors are unambiguous at any margin here — teal resolves to
#: teal alone, its runner-up 21 away — so a SEARCH always asks for exactly
#: one color. Only muted swatches come out ambiguous, which is honest: a
#: slate really is somewhere between charcoal and teal.
FAMILY_AMBIGUITY_MARGIN = 5.0

#: Below this chroma a swatch's nearest-name is decided by lightness rather
#: than by color, so the hue fallback applies. Above it, the name is trusted.
NAME_UNRELIABLE_CHROMA = CHROMATIC_CHROMA

#: A swatch needs at least this much chroma for its hue angle to mean
#: anything. Under it the hue is numerical noise off the neutral axis, and
#: admitting it is how a grey hat starts matching pink.
MIN_HUE_CHROMA = 6.0

#: How far apart two hue angles may be and still be the same color.
MAX_HUE_DELTA = 25.0

#: Families the hue fallback must never bridge, whatever the angle says.
#:
#: CIELAB's hue angle is famously non-linear through the blue region —
#: straight lines bend toward purple — so a navy and a purple can land within
#: a few degrees of each other while looking nothing alike. This is a defect
#: of the color space, not a judgement call, and it is the same defect that
#: put palette blue ΔE 16.5 from purple under the old cutoff.
_INCOMPATIBLE_FAMILIES: frozenset[frozenset[str]] = frozenset({
    frozenset({"blue", "purple"}),
})


def color_family(name: str | None) -> frozenset[str]:
    """The basic color words for a palette name; empty if it isn't one.

    Empty means "not a curated name" — treated as unknown rather than as a
    family of its own, so unrecognised values never silently group together.
    """
    return _COLOR_FAMILIES.get((name or "").strip().lower(), frozenset())


def families_of_lab(lab: tuple[float, float, float]) -> frozenset[str]:
    """Every basic color word that could reasonably describe this color.

    Classifies against the curated palette and keeps every entry within
    `FAMILY_AMBIGUITY_MARGIN` of the nearest, so a color the palette cannot
    decide about is reported as belonging to all its candidates rather than
    to whichever one happened to win by half a unit.
    """
    scored = sorted(
        (lab_distance(lab, lab_of(f"#{r:02x}{g:02x}{b:02x}")), name)
        for name, (r, g, b) in _PALETTE
    )
    if not scored:
        return frozenset()
    cutoff = scored[0][0] + FAMILY_AMBIGUITY_MARGIN
    out: set[str] = set()
    for distance, name in scored:
        if distance > cutoff:
            break
        out |= color_family(name)
    return frozenset(out)


def hue_of(lab: tuple[float, float, float]) -> float:
    """Hue angle in degrees. Survives darkening and desaturation."""
    _l, a, b = lab
    return math.degrees(math.atan2(b, a)) % 360


def _hue_gap(lab_a: tuple[float, float, float], lab_b: tuple[float, float, float]) -> float:
    gap = abs(hue_of(lab_a) - hue_of(lab_b)) % 360
    return min(gap, 360 - gap)


def is_same_color(
    target_lab: tuple[float, float, float],
    swatch_lab: tuple[float, float, float],
    swatch_name: str | None = None,
) -> bool:
    """Whether a swatch is the color being searched for.

    Membership, decided categorically — see the long note in
    `search_service` for why no distance threshold can do this job.

    Two ways to qualify, and the second exists for one specific failure of
    the first. Nearest-name classification is driven by ΔE, which is
    dominated by LIGHTNESS: a dark teal at L=21 lands nearest charcoal
    because it is dark, not because it is grey. Its hue angle, though, is
    197° — the same as a mid teal's. So when a swatch is too muted for its
    name to be trustworthy, the hue answers instead, which is exactly the
    axis that survives being darkened.
    """
    stored = color_family(swatch_name)
    swatch_families = stored or families_of_lab(swatch_lab)
    target_families = families_of_lab(target_lab)
    if swatch_families & target_families:
        return True

    # Hue fallback, for muted swatches only.
    swatch_chroma = chroma_of(swatch_lab)
    if swatch_chroma >= NAME_UNRELIABLE_CHROMA or swatch_chroma < MIN_HUE_CHROMA:
        return False
    if chroma_of(target_lab) < CHROMATIC_CHROMA:
        return False  # a muted target claims nothing about a muted swatch
    # The chroma RATIO decides whether this swatch has enough of the target's
    # color to be a muted version of it rather than a neutral near it. It is
    # the same test, and the same constant, that keeps a blue-grey from
    # matching purple — and it is what separates the two cases the hue angle
    # alone cannot: a dark teal holds 41% of teal's chroma, a blue-grey 20%
    # of blue's, and their absolute chromas are 11.1 and 11.7.
    if is_neutral_mismatch(target_lab, swatch_lab):
        return False
    if any(
        swatch_families & pair and target_families & pair
        for pair in _INCOMPATIBLE_FAMILIES
    ):
        return False
    return _hue_gap(target_lab, swatch_lab) <= MAX_HUE_DELTA


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
