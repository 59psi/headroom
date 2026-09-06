import asyncio
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from PIL import Image, UnidentifiedImageError
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
    LogoStatus,
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
from headroom.utils import branding
from headroom.utils.upload import copy_upload_capped

router = APIRouter(prefix="/api/settings", tags=["settings"])

LOGO_MAX_HEIGHT = 96


# ---------------------------- Logo ----------------------------------- #


def _logo_status() -> LogoStatus:
    logo = branding.find_logo()
    return LogoStatus(logo_path=f"branding/{logo.name}" if logo else None)


@router.get("/logo", response_model=LogoStatus)
async def get_logo():
    return _logo_status()


def _encode_logo_sync(tmp_path: Path, staging: Path) -> None:
    """Decode, resize and re-encode the upload as PNG — into `staging`, not
    into place. Sync; runs under `to_thread`."""
    with Image.open(tmp_path) as img:
        # Always written as PNG so transparency survives; only opaque modes
        # need the RGB conversion first.
        if img.mode not in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        if img.height > LOGO_MAX_HEIGHT:
            ratio = LOGO_MAX_HEIGHT / img.height
            img = img.resize((int(img.width * ratio), LOGO_MAX_HEIGHT), Image.LANCZOS)
        img.save(staging, "PNG", optimize=True)


@router.post("/logo", response_model=LogoStatus)
async def upload_logo(photo: UploadFile):
    """Replace the site logo.

    The old logo is removed only AFTER the new one has been read, decoded and
    written to a staging file. It used to be deleted first — before the size
    cap and before Pillow opened the bytes — so a 413 (too large) or a corrupt
    file (a PNG content-type on bytes that were not a PNG) destroyed the logo
    that was already there, and the corrupt case also 500'd. Nothing in the
    suite seeded a prior logo, so the loss was invisible.

    The read and the Pillow work run off the event loop; both are blocking.
    """
    if not validate_image_content_type(photo.content_type):
        raise HTTPException(status_code=400, detail="Invalid image type")

    branding_dir = branding.branding_dir()
    branding_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(photo.filename or "logo.png").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
    staging = branding_dir / ".logo.png.tmp"
    try:
        with tmp_path.open("wb") as fh:
            await asyncio.to_thread(copy_upload_capped, photo, fh, what="Logo")
        try:
            await asyncio.to_thread(_encode_logo_sync, tmp_path, staging)
        except (UnidentifiedImageError, OSError) as exc:
            raise HTTPException(
                status_code=400, detail="That file is not an image Headroom can read."
            ) from exc
        # Only now is there something to replace the old logo WITH.
        branding.remove_logo()
        out_path = branding_dir / f"{branding.LOGO_STEM}.png"
        os.replace(staging, out_path)
    finally:
        tmp_path.unlink(missing_ok=True)
        staging.unlink(missing_ok=True)

    return LogoStatus(logo_path=f"branding/{out_path.name}")


@router.delete("/logo", status_code=204)
async def delete_logo():
    branding.remove_logo()


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
        **asdict(status),
        ca_changed=changed,
        ca_expected_sha256=expected,
        # A leaf can be short because it is old, or because its ISSUER is about
        # to expire and Caddy clamped it. Identical on the certificate,
        # opposite fixes — and the card used to advise the one that loops.
        issuer_not_after=ca_vault.issuer_expiry(),
        clamped_by_issuer=ca_vault.clamped_by_issuer(status.not_after),
    )


@router.get("/mdns", response_model=MdnsStatus)
async def get_mdns_status():
    """Read-only — LAN discovery is configured via HEADROOM_MDNS_* env vars."""
    return MdnsStatus(**mdns_service.mdns_status())


# ---------------------------- Claude model -------------------------- #


@router.get("/model", response_model=ModelStatus)
async def get_model(db: AsyncSession = Depends(get_db)):
    model_id, source = await settings_service.get_anthropic_model(db)
    return ModelStatus(model_id=model_id, source=source, default_model_id=settings.anthropic_model)


@router.put("/model", response_model=ModelStatus, dependencies=[Depends(require_admin)])
async def set_model(data: ModelUpdate, db: AsyncSession = Depends(get_db)):
    await settings_service.set_anthropic_model(db, data.model_id)
    model_id, source = await settings_service.get_anthropic_model(db)
    return ModelStatus(model_id=model_id, source=source, default_model_id=settings.anthropic_model)


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
