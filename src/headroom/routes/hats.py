import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings
from headroom.database import get_db
from headroom.models.hat_color import HatColor
from headroom.schemas.hat import ColorTag, ColorsUpdate, HatAssign, HatCreate, HatRead, HatUpdate
from headroom.services import hat_service
from headroom.services.color_service import extract_colors
from headroom.utils.photo import generate_filename, process_image, validate_image_content_type

router = APIRouter(prefix="/api/hats", tags=["hats"])


def _hat_to_read(hat) -> HatRead:
    return HatRead(
        id=hat.id,
        case_id=hat.case_id,
        position_in_case=hat.position_in_case,
        display_id=hat.display_id,
        case_display_id=hat.case.display_id if hat.case else None,
        photo_path=hat.photo_path,
        condition=hat.condition,
        date_last_worn=hat.date_last_worn,
        size=hat.size,
        style=hat.style,
        is_beanie=hat.is_beanie,
        colors=[
            ColorTag(
                color_name=c.color_name,
                hex_value=c.hex_value,
                dominance_rank=c.dominance_rank,
            )
            for c in (hat.colors or [])
        ],
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
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    hats = await hat_service.list_hats(db, case_id, style, condition, offset, limit)
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
            hex_value=c.hex_value,
            dominance_rank=c.dominance_rank,
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
    final_path = process_image(tmp_path, output_path)
    tmp_path.unlink(missing_ok=True)

    # Delete old photo
    if hat.photo_path:
        old_path = settings.upload_dir / hat.photo_path
        old_path.unlink(missing_ok=True)

    hat.photo_path = f"hats/{final_path.name}"

    # Extract colors and replace existing
    for color in list(hat.colors):
        await db.delete(color)

    color_data = extract_colors(final_path)
    for cd in color_data:
        db.add(HatColor(hat_id=hat.id, **cd))

    await db.commit()
    db.expire_all()
    return _hat_to_read(await hat_service.get_hat(db, hat_id))
