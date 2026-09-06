"""Where the site logo lives, once.

Three modules answered "which file is the logo" with three lists, and one had
drifted: `routes/settings` omitted `.jpeg` and compared suffixes case-sensitively
while `routes/public` and the branding seed in `app.py` accepted it. So a
`logo.jpeg` dropped into the volume was served to the login page, invisible to
`GET /api/settings/logo`, and never removed by an upload — `public`'s `sorted()`
then kept serving the old file beside the new one.
"""

from __future__ import annotations

from pathlib import Path

from headroom.config import settings

#: Every extension a logo may carry. Uploads are always re-encoded to PNG; the
#: others are files an operator placed in the volume by hand.
LOGO_SUFFIXES: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp")
LOGO_STEM = "logo"


def branding_dir() -> Path:
    return settings.upload_dir / "branding"


def find_logo() -> Path | None:
    """The logo file, or None. Deterministic when several exist (sorted)."""
    directory = branding_dir()
    if not directory.is_dir():
        return None
    for f in sorted(directory.iterdir()):
        if f.stem == LOGO_STEM and f.suffix.lower() in LOGO_SUFFIXES:
            return f
    return None


def remove_logo() -> None:
    """Delete EVERY logo variant, so a replacement cannot sit beside a stale one."""
    directory = branding_dir()
    if not directory.is_dir():
        return
    for f in directory.iterdir():
        if f.stem == LOGO_STEM and f.suffix.lower() in LOGO_SUFFIXES:
            f.unlink(missing_ok=True)
