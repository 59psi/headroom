import asyncio
import uuid
from pathlib import Path

from PIL import Image

MAX_DIMENSION = 1200


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


async def process_image_async(input_path: Path, output_path: Path) -> Path:
    """Async wrapper around process_image — runs Pillow off the event loop."""
    return await asyncio.to_thread(process_image, input_path, output_path)


def validate_image_content_type(content_type: str | None) -> bool:
    allowed = {"image/jpeg", "image/png", "image/heic", "image/heif", "image/webp"}
    return content_type in allowed
