import tempfile
from pathlib import Path

import webcolors
from colorthief import ColorThief
from PIL import Image


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _classify_color(r: int, g: int, b: int) -> str:
    """Find the closest CSS3 named color by Euclidean distance."""
    min_dist = float("inf")
    best_name = "unknown"
    for name in webcolors.names("css3"):
        nr, ng, nb = webcolors.hex_to_rgb(webcolors.name_to_hex(name, spec="css3"))
        dist = (r - nr) ** 2 + (g - ng) ** 2 + (b - nb) ** 2
        if dist < min_dist:
            min_dist = dist
            best_name = name
    return best_name


def _center_crop(image_path: Path) -> Path:
    """Crop to center 50% of the image and return path to a temp file."""
    img = Image.open(image_path)
    w, h = img.size
    left = w // 4
    top = h // 4
    right = w - left
    bottom = h - top
    cropped = img.crop((left, top, right, bottom))

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    cropped.save(tmp.name, "JPEG")
    tmp.close()
    return Path(tmp.name)


def extract_colors(image_path: Path, count: int = 3) -> list[dict]:
    """Extract dominant colors from the center of an image.

    Returns list of {color_name, hex_value, dominance_rank}.
    """
    cropped_path = _center_crop(image_path)
    try:
        ct = ColorThief(str(cropped_path))
        try:
            palette = ct.get_palette(color_count=count, quality=5)
        except Exception:
            try:
                dominant = ct.get_color(quality=5)
                palette = [dominant]
            except Exception:
                return []
    finally:
        cropped_path.unlink(missing_ok=True)

    results = []
    for rank, (r, g, b) in enumerate(palette, 1):
        results.append({
            "color_name": _classify_color(r, g, b),
            "hex_value": _rgb_to_hex(r, g, b),
            "dominance_rank": rank,
        })

    return results
