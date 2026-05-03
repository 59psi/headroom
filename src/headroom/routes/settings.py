import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.auth import require_admin
from headroom.config import settings
from headroom.database import get_db
from headroom.schemas.settings import (
    ApiKeyStatus,
    ApiKeyTestResult,
    ApiKeyUpdate,
    ModelStatus,
    ModelUpdate,
)
from headroom.services import settings_service
from headroom.services.claude_analysis import verify_api_key
from headroom.utils.photo import validate_image_content_type

router = APIRouter(prefix="/api/settings", tags=["settings"])

LOGO_MAX_HEIGHT = 96


# ---------------------------- Logo ----------------------------------- #


def _get_logo_path() -> Path | None:
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

    existing = _get_logo_path()
    if existing:
        existing.unlink(missing_ok=True)

    suffix = Path(photo.filename or "logo.png").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(photo.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        img = Image.open(tmp_path)
        if img.mode in ("RGBA", "P", "LA"):
            out_ext = ".png"
            save_fmt = "PNG"
        else:
            img = img.convert("RGB")
            out_ext = ".png"
            save_fmt = "PNG"

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


# ---------------------------- API key -------------------------------- #


@router.get("/api-key", response_model=ApiKeyStatus)
async def get_api_key_status(db: AsyncSession = Depends(get_db)):
    key, source = await settings_service.get_anthropic_key(db)
    if not key:
        return ApiKeyStatus(configured=False)
    return ApiKeyStatus(
        configured=True,
        source=source,
        masked=settings_service.mask_key(key),
    )


@router.put("/api-key", response_model=ApiKeyStatus, dependencies=[Depends(require_admin)])
async def set_api_key(data: ApiKeyUpdate, db: AsyncSession = Depends(get_db)):
    await settings_service.set_anthropic_key(db, data.api_key)
    key, source = await settings_service.get_anthropic_key(db)
    return ApiKeyStatus(
        configured=bool(key),
        source=source,
        masked=settings_service.mask_key(key) if key else None,
    )


@router.delete("/api-key", status_code=204, dependencies=[Depends(require_admin)])
async def delete_api_key(db: AsyncSession = Depends(get_db)):
    await settings_service.clear_anthropic_key(db)


@router.post("/api-key/test", response_model=ApiKeyTestResult, dependencies=[Depends(require_admin)])
async def test_api_key(db: AsyncSession = Depends(get_db)):
    key, _source = await settings_service.get_anthropic_key(db)
    if not key:
        return ApiKeyTestResult(ok=False, detail="No API key configured.")
    model, _msrc = await settings_service.get_anthropic_model(db)
    ok, detail = await verify_api_key(key, model=model)
    return ApiKeyTestResult(ok=ok, detail=detail)


# ---------------------------- Claude model -------------------------- #


@router.get("/model", response_model=ModelStatus)
async def get_model(db: AsyncSession = Depends(get_db)):
    model_id, source = await settings_service.get_anthropic_model(db)
    return ModelStatus(model_id=model_id, source=source)


@router.put("/model", response_model=ModelStatus, dependencies=[Depends(require_admin)])
async def set_model(data: ModelUpdate, db: AsyncSession = Depends(get_db)):
    await settings_service.set_anthropic_model(db, data.model_id)
    model_id, source = await settings_service.get_anthropic_model(db)
    return ModelStatus(model_id=model_id, source=source)


@router.delete("/model", status_code=204, dependencies=[Depends(require_admin)])
async def clear_model(db: AsyncSession = Depends(get_db)):
    """Reset to env / built-in default."""
    await settings_service.clear_anthropic_model(db)
