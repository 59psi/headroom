import asyncio
import logging
import uuid
from pathlib import Path

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

MAX_DIMENSION = 1200

# Gallery tiles render at roughly 160 CSS px, so 320 covers a 2x display and
# nothing more. The full cutout is a 1200px RGBA PNG — a few hundred KB each,
# which is fine for one hat page and ruinous for a grid of fifty.
THUMB_DIMENSION = 320
THUMBS_DIR = "thumbs"

# The export derivative: bigger than the grid thumbnail, because a zip you hand
# someone gets opened on a laptop and 320px looks soft there. 800px at q82 is
# roughly 3x the bytes of a thumbnail and still small enough that a few hundred
# hats stay comfortably emailable.
#
# WebP, and the reasoning is worth recording because "use the universal
# format" is the right instinct and lands somewhere else here.
#
# WebP is not proprietary: open spec, royalty-free, BSD-licensed reference
# implementation, and supported everywhere since Safari 14 in 2020 (~97%).
# The genuinely older options both cost something real, because these photos
# are transparent cutouts and alpha is the point:
#
#     format                per image   x300 hats   alpha
#     PNG lossless            137 KB      40 MB      yes
#     PNG 256-color           26 KB     7.7 MB      yes, edges soften
#     JPEG q85                 31 KB     8.9 MB      NO — hats stop floating
#     WebP q82                  9 KB     2.6 MB      yes
#
# AVIF measures 13.5 KB against WebP's 13.9 on photographic content — a few
# percent, not the ~30% it manages on flat synthetic images — so it buys
# nothing here worth the Safari 16.4 floor.
EXPORT_DIMENSION = 800
EXPORT_QUALITY = 82
EXPORT_DIR = "export"


def generate_filename(original_filename: str) -> str:
    ext = Path(original_filename).suffix.lower()
    return f"{uuid.uuid4().hex}{ext}"


def process_image(input_path: Path, output_path: Path) -> Path:
    """Resize and convert to JPEG. Returns the final output path.

    Synchronous — call from sync code, or wrap in `asyncio.to_thread` from
    async code so Pillow's CPU work doesn't block the event loop.
    """
    try:
        import pillow_heif  # noqa: PLC0415
        pillow_heif.register_heif_opener()
    except ImportError:
        pass

    # Context manager, like the two encoders below (this one held its handle
    # until GC). `exif_transpose` FIRST: a phone shoots portrait with the
    # sensor sideways and records Orientation 6/8 in EXIF; `.convert("RGB")`
    # + JPEG save drops that tag without honoring it, so the stored photo — and
    # the cutout, the thumbnail and everything Claude sees — was on its side.
    with Image.open(input_path) as opened:
        img = ImageOps.exif_transpose(opened) or opened
        if img.mode != "RGB":
            img = img.convert("RGB")

        if max(img.size) > MAX_DIMENSION:
            img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

        final_path = output_path.with_suffix(".jpg")
        img.save(final_path, "JPEG", quality=85, optimize=True)
    return final_path


def make_thumbnail(source_path: Path, dest_path: Path) -> Path | None:
    """Write a small WebP copy of a hat photo. Returns the path, or None.

    WebP because these are transparent PNGs: it keeps the alpha channel (the
    hats float on the canvas, so a flattened JPEG thumbnail is not an option)
    at a fraction of the size. Lossy at quality 80 — invisible at 160 CSS px.

    Best-effort by design. A gallery falling back to full-size images is slow;
    an upload that fails because a thumbnail could not be written is broken.
    """
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source_path) as img:
            # Preserve alpha; RGBA is what a cutout is, and P-mode with
            # transparency needs converting before resize or the edges fringe.
            if img.mode not in ("RGBA", "RGB"):
                img = img.convert("RGBA")
            img.thumbnail((THUMB_DIMENSION, THUMB_DIMENSION), Image.LANCZOS)
            final = dest_path.with_suffix(".webp")
            img.save(final, "WEBP", quality=80, method=4)
        return final
    except Exception as exc:  # noqa: BLE001 — a missing thumbnail must never fail an upload
        # Best-effort still gets a voice. This returned None with no record, so
        # a thumbnail pipeline failing on every hat (disk full, a Pillow build
        # without WebP) was indistinguishable from "already existed".
        logger.warning("Thumbnail failed for %s: %s", source_path, exc)
        return None


def export_derivative_path(upload_dir: Path, photo_rel: str) -> Path:
    """Where the export image for `photo_rel` lives (whether or not it exists).

    One definition, because two callers need it and they need to AGREE: the
    export builds it, and the photo-replacement path deletes it. Computing the
    same path in both places is how the delete quietly stops matching the build
    and every re-shot hat starts leaking a file.
    """
    return (upload_dir / "hats" / EXPORT_DIR / Path(photo_rel).stem).with_suffix(".webp")


def make_export_image(source_path: Path, dest_path: Path) -> Path | None:
    """Write an export-sized WebP copy of a hat photo. Returns the path, or None.

    Same contract and same best-effort rule as `make_thumbnail`: a missing
    export image costs one photo in the zip, never the whole download.

    Generated from the CANONICAL photo, not from the thumbnail — upscaling a
    320px thumbnail to 800 would produce a larger file that looks worse than
    the thumbnail it came from.
    """
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source_path) as img:
            if img.mode not in ("RGBA", "RGB"):
                img = img.convert("RGBA")
            img.thumbnail((EXPORT_DIMENSION, EXPORT_DIMENSION), Image.LANCZOS)
            final = dest_path.with_suffix(".webp")
            # method=6 is the slowest/smallest WebP effort. Worth it here and
            # not for thumbnails: this runs once per hat per export, and the
            # bytes are what someone downloads.
            img.save(final, "WEBP", quality=EXPORT_QUALITY, method=6)
        return final
    except Exception as exc:  # noqa: BLE001 — one bad photo must not fail an export
        logger.warning("Export image failed for %s: %s", source_path, exc)
        return None


async def make_thumbnail_async(source_path: Path, dest_path: Path) -> Path | None:
    """Async wrapper — Pillow encode is CPU-bound and must stay off the loop."""
    return await asyncio.to_thread(make_thumbnail, source_path, dest_path)


async def make_export_image_async(source_path: Path, dest_path: Path) -> Path | None:
    """Async wrapper — same reason as `make_thumbnail_async`, more so.

    This one decodes a full-resolution photo and re-encodes it at WebP
    `method=6`, the slowest effort setting. It is the single most expensive
    per-hat operation outside rembg, and running it on the event loop stops
    the whole app for the duration.
    """
    return await asyncio.to_thread(make_export_image, source_path, dest_path)


async def process_image_async(input_path: Path, output_path: Path) -> Path:
    """Async wrapper around process_image — runs Pillow off the event loop."""
    return await asyncio.to_thread(process_image, input_path, output_path)


def validate_image_content_type(content_type: str | None) -> bool:
    allowed = {"image/jpeg", "image/png", "image/heic", "image/heif", "image/webp"}
    return content_type in allowed
