import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings
from headroom.database import get_db
from headroom.schemas.case import CaseCreate, CaseDetail, CaseRead, CaseUpdate, HatSummary
from headroom.services import capacity as capacity_rules
from headroom.services import case_service
from headroom.utils.photo import (
    generate_filename,
    process_image_async,
    validate_image_content_type,
)
from headroom.utils.upload import copy_upload_capped

router = APIRouter(prefix="/api/cases", tags=["cases"])


def _case_to_read(case) -> CaseRead:
    # Disposed hats free their slot, so they must not count toward occupancy —
    # `_validate_capacity` filters them, and a read model that didn't would
    # show a case as fuller than the validator considers it.
    hats = [h for h in (case.hats or []) if h.disposed_at is None]
    beanie_count = sum(1 for h in hats if h.is_beanie)
    room = capacity_rules.evaluate(
        capacity=case.capacity,
        beanie_count=beanie_count,
        regular_count=len(hats) - beanie_count,
    )
    return CaseRead(
        id=case.id,
        case_type=case.case_type,
        sequence_number=case.sequence_number,
        display_id=case.display_id,
        photo_path=case.photo_path,
        capacity=case.capacity,
        hat_count=len(hats),
        beanie_count=beanie_count,
        regular_count=len(hats) - beanie_count,
        room_id=case.room_id,
        room_name=case.room.name if case.room else "Unknown",
        accepts_regular=room.accepts_regular,
        accepts_beanie=room.accepts_beanie,
        free_regular=room.free_regular,
        free_beanie=room.free_beanie,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _case_to_detail(case) -> CaseDetail:
    # CaseDetail is CaseRead plus the hat list — derive the shared fields rather
    # than restating all 13 of them (they drifted apart too easily).
    return CaseDetail(
        **_case_to_read(case).model_dump(),
        hats=[
            HatSummary(
                id=h.id,
                display_id=h.display_id,
                style=h.style,
                is_beanie=h.is_beanie,
                photo_path=h.photo_path,
                thumb_path=h.thumb_path,
            )
            for h in (case.hats or [])
        ],
    )


@router.post("", response_model=CaseRead, status_code=201)
async def create_case(data: CaseCreate, db: AsyncSession = Depends(get_db)):
    case = await case_service.create_case(db, data)
    return _case_to_read(case)


@router.get("", response_model=list[CaseRead])
async def list_cases(db: AsyncSession = Depends(get_db)):
    cases = await case_service.list_cases(db)
    return [_case_to_read(c) for c in cases]


@router.get("/{display_id}", response_model=CaseDetail)
async def get_case(display_id: str, db: AsyncSession = Depends(get_db)):
    case = await case_service.get_case_by_display_id(db, display_id)
    return _case_to_detail(case)


@router.put("/{display_id}", response_model=CaseRead)
async def update_case(
    display_id: str, data: CaseUpdate, db: AsyncSession = Depends(get_db)
):
    case = await case_service.update_case(db, display_id, data)
    return _case_to_read(case)


@router.delete("/{display_id}", status_code=204)
async def delete_case(display_id: str, db: AsyncSession = Depends(get_db)):
    await case_service.delete_case(db, display_id)


@router.post("/{display_id}/photo", response_model=CaseRead)
async def upload_case_photo(
    display_id: str,
    photo: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    if not validate_image_content_type(photo.content_type):
        raise HTTPException(status_code=400, detail="Invalid image type")

    case = await case_service.get_case_by_display_id(db, display_id)

    # Save to temp, process, move to uploads
    upload_dir = settings.upload_dir / "cases"
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = generate_filename(photo.filename or "photo.jpg")
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as tmp:
        copy_upload_capped(photo, tmp, what="Photo")
        tmp_path = Path(tmp.name)

    output_path = upload_dir / filename
    try:
        final_path = await process_image_async(tmp_path, output_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    # Delete old photo if exists
    if case.photo_path:
        old_path = settings.upload_dir / case.photo_path
        old_path.unlink(missing_ok=True)

    case.photo_path = f"cases/{final_path.name}"
    await db.commit()
    await db.refresh(case)
    return _case_to_read(case)
