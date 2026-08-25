import asyncio
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
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
    TlsStatusRead,
    ModelStatus,
    ModelUpdate,
    GuestViewStatus,
    GuestViewUpdate,
    TagBaseStatus,
    TagBaseUpdate,
)
from headroom.services import (
    activity_service,
    ca_vault,
    guest_view_service,
    mdns_service,
    tls_health,
    settings_service,
    tag_service,
)
from headroom.services.claude_analysis import verify_api_key
from headroom.utils.photo import validate_image_content_type
from headroom.utils.upload import copy_upload_capped

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
        copy_upload_capped(photo, tmp, what="Logo")
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


# ------------------------ TLS / mDNS status -------------------------- #


@router.get("/tls", response_model=TlsStatusRead)
async def get_tls_status(db: AsyncSession = Depends(get_db)):
    """What certificate the HTTPS front door is actually serving.

    Opens a TLS connection to the app's own origin rather than reading Caddy's
    storage, because those can disagree: the failure this was written for had a
    valid certificate on disk and an expired one in Caddy's memory, and only
    the served chain is what a browser sees.

    Run off the event loop — it is a network round trip, short but not free.
    """
    status = await asyncio.to_thread(tls_health.check_certificate)

    # Has the trust anchor itself been replaced? Caddy names every root
    # `Caddy Local Authority - <year> ECC Root`, so a regenerated CA looks
    # identical by eye to the one every device installed by hand — the first
    # symptom is a device reporting an invalid signature on a chain the server
    # considers perfect. Compared against the fingerprint recorded on first
    # sight, so the change is reported the hour it happens.
    changed, expected = await ca_vault.check_root(db, status.ca_sha256)
    return TlsStatusRead(
        **asdict(status), ca_changed=changed, ca_expected_sha256=expected
    )


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


# ---------------------------- Tag base URL --------------------------- #


async def _tag_status(db: AsyncSession, request: Request) -> TagBaseStatus:
    base, source = await tag_service.get_tag_base(db, str(request.base_url))
    return TagBaseStatus(
        base_url=base,
        source=source,
        # Hat 1 is not guaranteed to exist; this is a shape example, not a link.
        example_url=tag_service.tag_url(base, tag_service.HAT, 1),
    )


@router.get("/tags", response_model=TagBaseStatus)
async def get_tag_base(request: Request, db: AsyncSession = Depends(get_db)):
    """The host written into QR labels and NFC tags."""
    return await _tag_status(db, request)


@router.put("/tags", response_model=TagBaseStatus, dependencies=[Depends(require_admin)])
async def set_tag_base(
    data: TagBaseUpdate, request: Request, db: AsyncSession = Depends(get_db)
):
    await tag_service.set_tag_base(db, data.base_url)
    return await _tag_status(db, request)


@router.delete("/tags", status_code=204, dependencies=[Depends(require_admin)])
async def clear_tag_base(db: AsyncSession = Depends(get_db)):
    """Fall back to whatever host the request arrives on."""
    await tag_service.set_tag_base(db, None)


# ---------------------------- Guest view ----------------------------- #


@router.get("/guest-view", response_model=GuestViewStatus)
async def get_guest_view(db: AsyncSession = Depends(get_db)):
    """Whether anyone reaching the login screen may browse without an account."""
    return GuestViewStatus(enabled=await guest_view_service.is_enabled(db))


@router.put("/guest-view", response_model=GuestViewStatus, dependencies=[Depends(require_admin)])
async def set_guest_view(data: GuestViewUpdate, db: AsyncSession = Depends(get_db)):
    """Turn guest browsing on or off.

    Audited both ways: this is the switch that decides whether the collection
    is readable without an account, and "when did that get turned on" is a
    question the log should be able to answer.
    """
    await guest_view_service.set_enabled(db, data.enabled)
    await activity_service.log_activity(
        db,
        kind="settings.guest_view",
        entity_type="system",
        entity_id=None,
        summary=f"Guest view {'enabled' if data.enabled else 'disabled'}",
    )
    await db.commit()
    return GuestViewStatus(enabled=await guest_view_service.is_enabled(db))
