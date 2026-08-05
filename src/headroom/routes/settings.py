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
    MdnsStatus,
    ModelStatus,
    ModelUpdate,
)
from headroom.services import activity_service, mdns_service, settings_service
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
        # Always written as PNG so transparency survives; only opaque modes
        # need the RGB conversion first.
        if img.mode not in ("RGBA", "P", "LA"):
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


# ---------------------------- API keys -------------------------------- #
# Anthropic (analysis) and Google Vision (fallback brand logos) expose the
# identical GET status / PUT set / DELETE clear triple, so the routes are
# generated once per provider instead of copied. The raw key is never returned
# — only ApiKeyStatus (configured / source / masked prefix+suffix).


def _mount_key_routes(provider: settings_service.KeyProvider) -> None:
    path = f"/{provider.slug}"

    async def status(db: AsyncSession) -> ApiKeyStatus:
        key, source = await settings_service.get_key(db, provider)
        if not key:
            return ApiKeyStatus(configured=False)
        return ApiKeyStatus(
            configured=True,
            source=source,
            masked=settings_service.mask_key(key),
        )

    @router.get(path, response_model=ApiKeyStatus, name=f"get_{provider.name}_status")
    async def get_key_status(db: AsyncSession = Depends(get_db)):
        return await status(db)

    @router.put(
        path,
        response_model=ApiKeyStatus,
        dependencies=[Depends(require_admin)],
        name=f"set_{provider.name}",
    )
    async def set_key(data: ApiKeyUpdate, db: AsyncSession = Depends(get_db)):
        await settings_service.set_key(db, provider, data.api_key)
        await activity_service.log_activity(
            db, kind="settings.key_set", entity_type="system", entity_id=None,
            summary=f"{provider.label} set/updated",
        )
        await db.commit()
        return await status(db)

    @router.delete(
        path,
        status_code=204,
        dependencies=[Depends(require_admin)],
        name=f"delete_{provider.name}",
    )
    async def delete_key(db: AsyncSession = Depends(get_db)):
        await settings_service.clear_key(db, provider)
        await activity_service.log_activity(
            db, kind="settings.key_cleared", entity_type="system", entity_id=None,
            summary=f"{provider.label} cleared",
        )
        await db.commit()


for _provider in (settings_service.ANTHROPIC_KEY, settings_service.GOOGLE_VISION_KEY):
    _mount_key_routes(_provider)


@router.post("/api-key/test", response_model=ApiKeyTestResult, dependencies=[Depends(require_admin)])
async def test_api_key(db: AsyncSession = Depends(get_db)):
    """Anthropic-only: the Vision key has no equivalent cheap probe."""
    key, _source = await settings_service.get_anthropic_key(db)
    if not key:
        return ApiKeyTestResult(ok=False, detail="No API key configured.")
    model, _msrc = await settings_service.get_anthropic_model(db)
    ok, detail = await verify_api_key(key, model=model)
    return ApiKeyTestResult(ok=ok, detail=detail)


# ---------------------------- mDNS status ---------------------------- #


@router.get("/mdns", response_model=MdnsStatus)
async def get_mdns_status():
    """Read-only — LAN discovery is configured via HEADROOM_MDNS_* env vars."""
    return MdnsStatus(**mdns_service.mdns_status())


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
