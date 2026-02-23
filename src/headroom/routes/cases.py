import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings
from headroom.database import get_db
from headroom.schemas.case import CaseCreate, CaseDetail, CaseRead, CaseUpdate, HatSummary
from headroom.services import case_service
from headroom.utils.photo import generate_filename, process_image, validate_image_content_type

router = APIRouter(prefix="/api/cases", tags=["cases"])


def _case_to_read(case) -> CaseRead:
    hats = case.hats or []
    beanie_count = sum(1 for h in hats if h.is_beanie)
    return CaseRead(
        id=case.id,
        case_type=case.case_type,
        sequence_number=case.sequence_number,
        display_id=case.display_id,
        photo_path=case.photo_path,
        hat_count=len(hats),
        beanie_count=beanie_count,
        regular_count=len(hats) - beanie_count,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _case_to_detail(case) -> CaseDetail:
    hats = case.hats or []
    beanie_count = sum(1 for h in hats if h.is_beanie)
    return CaseDetail(
        id=case.id,
        case_type=case.case_type,
        sequence_number=case.sequence_number,
        display_id=case.display_id,
        photo_path=case.photo_path,
        hat_count=len(hats),
        beanie_count=beanie_count,
        regular_count=len(hats) - beanie_count,
        created_at=case.created_at,
        updated_at=case.updated_at,
        hats=[
            HatSummary(
                id=h.id,
                display_id=h.display_id,
                style=h.style,
                is_beanie=h.is_beanie,
                photo_path=h.photo_path,
            )
            for h in hats
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
        shutil.copyfileobj(photo.file, tmp)
        tmp_path = Path(tmp.name)

    output_path = upload_dir / filename
    final_path = process_image(tmp_path, output_path)
    tmp_path.unlink(missing_ok=True)

    # Delete old photo if exists
    if case.photo_path:
        old_path = settings.upload_dir / case.photo_path
        old_path.unlink(missing_ok=True)

    case.photo_path = f"cases/{final_path.name}"
    await db.commit()
    await db.refresh(case)
    return _case_to_read(case)
