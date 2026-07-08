import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings
from headroom.database import get_db
from headroom.models.hat_color import HatColor
from headroom.schemas.hat import (
    ColorTag,
    ColorsUpdate,
    HatAssign,
    HatCreate,
    HatDispose,
    HatRead,
    HatUpdate,
)
from headroom.services import hat_service, settings_service
from headroom.services.claude_analysis import ClaudeAnalysisError, analyze_hat_image
from headroom.services.hat_analysis_pipeline import (
    _apply_analysis,
    finalize_hat_photo,
    refresh_melin_resale,
    run_fallback_analysis,
)
from headroom.utils.photo import (
    generate_filename,
    process_image_async,
    validate_image_content_type,
)

router = APIRouter(prefix="/api/hats", tags=["hats"])


def _hat_to_read(hat) -> HatRead:
    room = hat.case.room if hat.case and hat.case.room else None
    return HatRead(
        id=hat.id,
        case_id=hat.case_id,
        position_in_case=hat.position_in_case,
        display_id=hat.display_id,
        case_display_id=hat.case.display_id if hat.case else None,
        case_type=hat.case.case_type if hat.case else None,
        photo_path=hat.photo_path,
        condition=hat.condition,
        date_last_worn=hat.date_last_worn,
        size=hat.size,
        style=hat.style,
        is_beanie=hat.is_beanie,
        colors=[
            ColorTag(
                color_name=c.color_name,
                general_color=c.general_color or "",
                hex_value=c.hex_value,
                dominance_rank=c.dominance_rank,
                tier=getattr(c, "tier", "primary") or "primary",
            )
            for c in (hat.colors or [])
        ],
        room_id=room.id if room else None,
        room_name=room.name if room else None,
        brand=hat.brand,
        model_name=hat.model_name,
        model_confidence=hat.model_confidence,
        style_descriptor=hat.style_descriptor,
        design_notes=hat.design_notes,
        estimated_new_price=hat.estimated_new_price,
        estimated_new_price_source=hat.estimated_new_price_source,
        resale_price=hat.resale_price,
        resale_price_source=hat.resale_price_source,
        resale_price_url=hat.resale_price_url,
        resale_checked_at=hat.resale_checked_at,
        analysis_status=hat.analysis_status,
        analysis_error=hat.analysis_error,
        analyzed_at=hat.analyzed_at,
        disposed_at=hat.disposed_at,
        disposed_via=hat.disposed_via,
        disposed_price=hat.disposed_price,
        disposed_to=hat.disposed_to,
        disposed_notes=hat.disposed_notes,
        ebay_avg_price=hat.ebay_avg_price,
        ebay_median_price=hat.ebay_median_price,
        ebay_listing_count=hat.ebay_listing_count,
        ebay_search_url=hat.ebay_search_url,
        ebay_checked_at=hat.ebay_checked_at,
        created_at=hat.created_at,
        updated_at=hat.updated_at,
    )


@router.post("", response_model=HatRead, status_code=201)
async def create_hat(data: HatCreate, db: AsyncSession = Depends(get_db)):
    hat = await hat_service.create_hat(db, data)
    return _hat_to_read(hat)


@router.get("", response_model=list[HatRead])
async def list_hats(
    case_id: int | None = Query(None),
    style: str | None = Query(None),
    condition: str | None = Query(None),
    status: str = Query("active", pattern="^(active|disposed|all)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    hats = await hat_service.list_hats(db, case_id, style, condition, status, offset, limit)
    return [_hat_to_read(h) for h in hats]


@router.get("/{hat_id}", response_model=HatRead)
async def get_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    hat = await hat_service.get_hat(db, hat_id)
    return _hat_to_read(hat)


@router.put("/{hat_id}", response_model=HatRead)
async def update_hat(
    hat_id: int, data: HatUpdate, db: AsyncSession = Depends(get_db)
):
    hat = await hat_service.update_hat(db, hat_id, data)
    return _hat_to_read(hat)


@router.delete("/{hat_id}", status_code=204)
async def delete_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    await hat_service.delete_hat(db, hat_id)


@router.patch("/{hat_id}/assign", response_model=HatRead)
async def assign_hat(
    hat_id: int, data: HatAssign, db: AsyncSession = Depends(get_db)
):
    hat = await hat_service.assign_hat(db, hat_id, data.case_id)
    return _hat_to_read(hat)


@router.post("/{hat_id}/dispose", response_model=HatRead)
async def dispose_hat(
    hat_id: int, data: HatDispose, db: AsyncSession = Depends(get_db)
):
    """Mark a hat as sold/gifted/lost/trashed/trade. Soft delete — undoable."""
    hat = await hat_service.dispose_hat(
        db, hat_id,
        via=data.via, price=data.price, to=data.to, notes=data.notes,
        disposed_at=data.disposed_at,
    )
    return _hat_to_read(hat)


@router.delete("/{hat_id}/dispose", response_model=HatRead)
async def undispose_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    """Restore a previously-disposed hat back to active status."""
    hat = await hat_service.undispose_hat(db, hat_id)
    return _hat_to_read(hat)


@router.put("/{hat_id}/colors", response_model=HatRead)
async def update_hat_colors(
    hat_id: int, data: ColorsUpdate, db: AsyncSession = Depends(get_db)
):
    hat = await hat_service.get_hat(db, hat_id)

    for color in list(hat.colors):
        await db.delete(color)

    for c in data.colors:
        db.add(HatColor(
            hat_id=hat.id,
            color_name=c.color_name,
            general_color=c.general_color or "",
            hex_value=c.hex_value,
            dominance_rank=c.dominance_rank,
            tier=c.tier or "primary",
        ))

    await db.commit()
    db.expire_all()
    return _hat_to_read(await hat_service.get_hat(db, hat_id))


@router.post("/{hat_id}/photo", response_model=HatRead)
async def upload_hat_photo(
    hat_id: int,
    photo: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    if not validate_image_content_type(photo.content_type):
        raise HTTPException(status_code=400, detail="Invalid image type")

    hat = await hat_service.get_hat(db, hat_id)

    upload_dir = settings.upload_dir / "hats"
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = generate_filename(photo.filename or "photo.jpg")
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as tmp:
        shutil.copyfileobj(photo.file, tmp)
        tmp_path = Path(tmp.name)

    output_path = upload_dir / filename
    try:
        final_path = await process_image_async(tmp_path, output_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    # Delete old photo
    if hat.photo_path:
        old_path = settings.upload_dir / hat.photo_path
        old_path.unlink(missing_ok=True)

    # Pipeline: bg removal + Claude analysis (in-place mutation of `hat`)
    await finalize_hat_photo(db, hat, final_path)
    await db.commit()
    db.expire_all()
    return _hat_to_read(await hat_service.get_hat(db, hat_id))


@router.post("/{hat_id}/reanalyze", response_model=HatRead)
async def reanalyze_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    """Re-run Claude analysis against the current photo without re-uploading."""
    hat = await hat_service.get_hat(db, hat_id)
    if not hat.photo_path:
        raise HTTPException(status_code=400, detail="Hat has no photo to analyze")
    photo_path = settings.upload_dir / hat.photo_path
    if not photo_path.exists():
        raise HTTPException(status_code=404, detail="Photo file missing on disk")

    # Re-running analysis re-uses the existing photo; bg removal already done.
    api_key, _source = await settings_service.get_anthropic_key(db)
    if not api_key:
        # No Claude — try the fallback (mask colors + Google logo brand).
        applied = await run_fallback_analysis(
            db, hat, photo_path, reason="No Anthropic API key configured"
        )
        if not applied:
            raise HTTPException(
                status_code=400,
                detail="No Anthropic API key configured (and no fallback data available)",
            )
        await db.commit()
        db.expire_all()
        return _hat_to_read(await hat_service.get_hat(db, hat_id))
    model_id, _msrc = await settings_service.get_anthropic_model(db)

    try:
        analysis = await analyze_hat_image(
            photo_path, api_key,
            model=model_id, selected_style=hat.style,
        )
    except ClaudeAnalysisError as exc:
        hat.analysis_status = "error"
        hat.analysis_error = str(exc)
        hat.analyzed_at = datetime.now(timezone.utc)
        await run_fallback_analysis(
            db, hat, photo_path, reason=f"Claude analysis failed: {exc}"
        )
        await db.commit()
        db.expire_all()
        return _hat_to_read(await hat_service.get_hat(db, hat_id))

    _apply_analysis(hat, analysis)
    await refresh_melin_resale(hat)
    await db.commit()
    db.expire_all()
    return _hat_to_read(await hat_service.get_hat(db, hat_id))
