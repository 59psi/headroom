import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from PIL import Image

from headroom.config import settings
from headroom.utils.photo import validate_image_content_type

router = APIRouter(prefix="/api/settings", tags=["settings"])

LOGO_MAX_HEIGHT = 96


def _get_logo_path() -> Path | None:
    """Find existing logo file in uploads/branding/."""
    branding_dir = settings.upload_dir / "branding"
    if not branding_dir.exists():
        return None
    for f in branding_dir.iterdir():
        if f.stem == "logo" and f.suffix in (".jpg", ".png", ".webp"):
            return f
    return None


@router.get("/logo")
async def get_logo():
    logo = _get_logo_path()
    if logo:
        return {"logo_path": f"branding/{logo.name}"}
    return {"logo_path": None}


@router.post("/logo")
async def upload_logo(photo: UploadFile):
    if not validate_image_content_type(photo.content_type):
        raise HTTPException(status_code=400, detail="Invalid image type")

    branding_dir = settings.upload_dir / "branding"
    branding_dir.mkdir(parents=True, exist_ok=True)

    # Remove existing logo
    existing = _get_logo_path()
    if existing:
        existing.unlink(missing_ok=True)

    # Save to temp
    suffix = Path(photo.filename or "logo.png").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(photo.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        img = Image.open(tmp_path)
        if img.mode in ("RGBA", "P", "LA"):
            # Keep transparency — save as PNG
            out_ext = ".png"
            save_fmt = "PNG"
        else:
            img = img.convert("RGB")
            out_ext = ".png"
            save_fmt = "PNG"

        # Resize proportionally to fit max height
        if img.height > LOGO_MAX_HEIGHT:
            ratio = LOGO_MAX_HEIGHT / img.height
            new_w = int(img.width * ratio)
            img = img.resize((new_w, LOGO_MAX_HEIGHT), Image.LANCZOS)

        out_path = branding_dir / f"logo{out_ext}"
        img.save(out_path, save_fmt, optimize=True)
    finally:
        tmp_path.unlink(missing_ok=True)

    return {"logo_path": f"branding/{out_path.name}"}


@router.delete("/logo", status_code=204)
async def delete_logo():
    existing = _get_logo_path()
    if existing:
        existing.unlink(missing_ok=True)
