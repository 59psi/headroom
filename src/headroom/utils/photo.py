import uuid
from pathlib import Path

from PIL import Image

MAX_DIMENSION = 1200


def generate_filename(original_filename: str) -> str:
    ext = Path(original_filename).suffix.lower()
    return f"{uuid.uuid4().hex}{ext}"


def process_image(input_path: Path, output_path: Path) -> Path:
    """Resize and convert to JPEG. Returns the final output path."""
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass

    img = Image.open(input_path)

    # Convert HEIC/HEIF or any format to RGB JPEG
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Resize if too large
    if max(img.size) > MAX_DIMENSION:
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

    # Always save as JPEG
    final_path = output_path.with_suffix(".jpg")
    img.save(final_path, "JPEG", quality=85, optimize=True)
    return final_path


def validate_image_content_type(content_type: str | None) -> bool:
    allowed = {"image/jpeg", "image/png", "image/heic", "image/heif", "image/webp"}
    return content_type in allowed
