from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.schemas.hat import HatCreate, HatStyle, HatUpdate

MAX_REGULAR = 4
MAX_BEANIE = 6


async def _reload_hat(db: AsyncSession, hat_id: int) -> Hat:
    db.expire_all()
    result = await db.execute(
        select(Hat)
        .options(selectinload(Hat.case), selectinload(Hat.colors))
        .where(Hat.id == hat_id)
    )
    return result.scalar_one()


async def _get_next_position(db: AsyncSession, case_id: int) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(Hat.position_in_case), 0)).where(
            Hat.case_id == case_id
        )
    )
    return result.scalar_one() + 1


async def _validate_capacity(
    db: AsyncSession, case_id: int, is_beanie: bool, exclude_hat_id: int | None = None
) -> None:
    query = select(Hat).where(Hat.case_id == case_id)
    if exclude_hat_id:
        query = query.where(Hat.id != exclude_hat_id)
    result = await db.execute(query)
    hats = list(result.scalars().all())

    if hats:
        existing_has_beanies = any(h.is_beanie for h in hats)
        existing_has_regular = any(not h.is_beanie for h in hats)
        if is_beanie and existing_has_regular:
            raise HTTPException(
                status_code=409,
                detail="Case already contains regular hats — cannot mix types",
            )
        if not is_beanie and existing_has_beanies:
            raise HTTPException(
                status_code=409,
                detail="Case already contains beanies — cannot mix types",
            )

    beanie_count = sum(1 for h in hats if h.is_beanie)
    regular_count = len(hats) - beanie_count

    if is_beanie and beanie_count >= MAX_BEANIE:
        raise HTTPException(
            status_code=409,
            detail=f"Case has reached max beanie capacity ({MAX_BEANIE})",
        )
    if not is_beanie and regular_count >= MAX_REGULAR:
        raise HTTPException(
            status_code=409,
            detail=f"Case has reached max regular hat capacity ({MAX_REGULAR})",
        )


async def create_hat(db: AsyncSession, data: HatCreate) -> Hat:
    is_beanie = data.style == HatStyle.beanie
    position = None

    if data.case_id is not None:
        case = await db.get(Case, data.case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        await _validate_capacity(db, data.case_id, is_beanie)
        position = await _get_next_position(db, data.case_id)

    hat = Hat(
        case_id=data.case_id,
        position_in_case=position,
        condition=data.condition,
        size=data.size,
        style=data.style,
        date_last_worn=data.date_last_worn,
        is_beanie=is_beanie,
    )
    db.add(hat)
    await db.commit()
    return await _reload_hat(db, hat.id)


async def list_hats(
    db: AsyncSession,
    case_id: int | None = None,
    style: str | None = None,
    condition: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[Hat]:
    query = (
        select(Hat)
        .options(selectinload(Hat.case), selectinload(Hat.colors))
    )
    if case_id is not None:
        query = query.where(Hat.case_id == case_id)
    if style:
        query = query.where(Hat.style == style)
    if condition:
        query = query.where(Hat.condition == condition)
    query = query.order_by(Hat.id).offset(offset).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_hat(db: AsyncSession, hat_id: int) -> Hat:
    result = await db.execute(
        select(Hat)
        .options(selectinload(Hat.case), selectinload(Hat.colors))
        .where(Hat.id == hat_id)
    )
    hat = result.scalar_one_or_none()
    if not hat:
        raise HTTPException(status_code=404, detail="Hat not found")
    return hat


async def update_hat(db: AsyncSession, hat_id: int, data: HatUpdate) -> Hat:
    hat = await get_hat(db, hat_id)
    update_data = data.model_dump(exclude_unset=True)

    if "style" in update_data:
        new_is_beanie = update_data["style"] == HatStyle.beanie
        if new_is_beanie != hat.is_beanie and hat.case_id is not None:
            await _validate_capacity(db, hat.case_id, new_is_beanie, exclude_hat_id=hat.id)
        hat.is_beanie = new_is_beanie

    for field, value in update_data.items():
        setattr(hat, field, value)

    await db.commit()
    return await _reload_hat(db, hat_id)


async def delete_hat(db: AsyncSession, hat_id: int) -> None:
    hat = await get_hat(db, hat_id)
    await db.delete(hat)
    await db.commit()


async def assign_hat(db: AsyncSession, hat_id: int, case_id: int | None) -> Hat:
    hat = await get_hat(db, hat_id)

    if case_id is not None:
        case = await db.get(Case, case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        await _validate_capacity(db, case_id, hat.is_beanie)
        position = await _get_next_position(db, case_id)
        hat.case_id = case_id
        hat.position_in_case = position
    else:
        hat.case_id = None
        hat.position_in_case = None

    await db.commit()
    return await _reload_hat(db, hat_id)
