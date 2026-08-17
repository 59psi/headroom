import asyncio
import uuid
from pathlib import Path

from PIL import Image

MAX_DIMENSION = 1200

# Gallery tiles render at roughly 160 CSS px, so 320 covers a 2x display and
# nothing more. The full cutout is a 1200px RGBA PNG — a few hundred KB each,
# which is fine for one hat page and ruinous for a grid of fifty.
THUMB_DIMENSION = 320
THUMBS_DIR = "thumbs"


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

    img = Image.open(input_path)
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
    except Exception:  # noqa: BLE001 — a missing thumbnail must never fail an upload
        return None


async def make_thumbnail_async(source_path: Path, dest_path: Path) -> Path | None:
    """Async wrapper — Pillow encode is CPU-bound and must stay off the loop."""
    return await asyncio.to_thread(make_thumbnail, source_path, dest_path)


async def process_image_async(input_path: Path, output_path: Path) -> Path:
    """Async wrapper around process_image — runs Pillow off the event loop."""
    return await asyncio.to_thread(process_image, input_path, output_path)


def validate_image_content_type(content_type: str | None) -> bool:
    allowed = {"image/jpeg", "image/png", "image/heic", "image/heif", "image/webp"}
    return content_type in allowed
