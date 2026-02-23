from pathlib import Path

from colorthief import ColorThief

# Simplified color mapping: RGB ranges to friendly names
COLOR_NAMES = [
    ((0, 0, 0), (50, 50, 50), "black"),
    ((200, 200, 200), (255, 255, 255), "white"),
    ((100, 100, 100), (200, 200, 200), "grey"),
    ((150, 0, 0), (255, 80, 80), "red"),
    ((200, 80, 0), (255, 180, 50), "orange"),
    ((200, 200, 0), (255, 255, 100), "yellow"),
    ((0, 100, 0), (100, 255, 100), "green"),
    ((0, 50, 100), (80, 150, 255), "blue"),
    ((0, 0, 100), (60, 60, 200), "navy blue"),
    ((100, 0, 100), (255, 100, 255), "purple"),
    ((150, 75, 0), (200, 150, 80), "brown"),
    ((200, 150, 150), (255, 200, 200), "pink"),
    ((0, 150, 150), (100, 255, 255), "teal"),
    ((150, 0, 0), (200, 50, 50), "maroon"),
    ((200, 200, 150), (255, 255, 200), "cream"),
    ((150, 150, 100), (200, 200, 150), "tan"),
]


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _classify_color(r: int, g: int, b: int) -> str:
    """Map RGB to a simplified color name using webcolors + heuristics."""
    try:
        import webcolors
        # Try exact CSS3 name first
        name = webcolors.rgb_to_name((r, g, b))
        return name
    except (ValueError, AttributeError):
        pass

    # Fall back to range-based classification
    best_name = "unknown"
    best_dist = float("inf")
    for low, high, name in COLOR_NAMES:
        if all(low[i] <= (r, g, b)[i] <= high[i] for i in range(3)):
            # Within range — compute distance to midpoint
            mid = tuple((low[i] + high[i]) / 2 for i in range(3))
            dist = sum((c - m) ** 2 for c, m in zip((r, g, b), mid))
            if dist < best_dist:
                best_dist = dist
                best_name = name

    if best_name == "unknown":
        # Fallback: find closest named color
        try:
            import webcolors
            min_dist = float("inf")
            for name_hex in webcolors.names("css3"):
                named_rgb = webcolors.name_to_hex(name_hex)
                nr, ng, nb = webcolors.hex_to_rgb(named_rgb)
                dist = (r - nr) ** 2 + (g - ng) ** 2 + (b - nb) ** 2
                if dist < min_dist:
                    min_dist = dist
                    best_name = name_hex
        except Exception:
            pass

    return best_name


def extract_colors(image_path: Path, count: int = 5) -> list[dict]:
    """Extract dominant colors from an image. Returns list of {color_name, hex_value, dominance_rank}."""
    ct = ColorThief(str(image_path))

    try:
        palette = ct.get_palette(color_count=count, quality=5)
    except Exception:
        # Single-color image or too small
        try:
            dominant = ct.get_color(quality=5)
            palette = [dominant]
        except Exception:
            return []

    results = []
    for rank, (r, g, b) in enumerate(palette, 1):
        results.append({
            "color_name": _classify_color(r, g, b),
            "hex_value": _rgb_to_hex(r, g, b),
            "dominance_rank": rank,
        })

    return results
