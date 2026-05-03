from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.schemas.hat import HatCreate, HatStyle, HatUpdate
from headroom.services.activity_service import log_activity

MAX_REGULAR = 4
MAX_BEANIE = 6

# Disposition `via` values accepted by the API.
DISPOSITION_VIAS = {"sold", "gifted", "lost", "trashed", "trade"}


async def _reload_hat(db: AsyncSession, hat_id: int) -> Hat:
    db.expire_all()
    result = await db.execute(
        select(Hat)
        .options(
            selectinload(Hat.case).selectinload(Case.room),
            selectinload(Hat.colors),
        )
        .where(Hat.id == hat_id)
    )
    return result.scalar_one()


async def _get_next_position(db: AsyncSession, case_id: int) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(Hat.position_in_case), 0)).where(
            Hat.case_id == case_id, Hat.disposed_at.is_(None)
        )
    )
    return result.scalar_one() + 1


async def _validate_capacity(
    db: AsyncSession, case_id: int, is_beanie: bool, exclude_hat_id: int | None = None
) -> None:
    # Disposed hats no longer occupy a slot.
    query = select(Hat).where(Hat.case_id == case_id, Hat.disposed_at.is_(None))
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
    await log_activity(
        db, kind="hat.created", entity_type="hat", entity_id=hat.id,
        summary=f"Hat #{hat.id} created · style={data.style} size={data.size}",
    )
    await db.commit()
    return await _reload_hat(db, hat.id)


async def list_hats(
    db: AsyncSession,
    case_id: int | None = None,
    style: str | None = None,
    condition: str | None = None,
    status: str = "active",
    offset: int = 0,
    limit: int = 50,
) -> list[Hat]:
    query = (
        select(Hat)
        .options(
            selectinload(Hat.case).selectinload(Case.room),
            selectinload(Hat.colors),
        )
    )
    if case_id is not None:
        query = query.where(Hat.case_id == case_id)
    if style:
        query = query.where(Hat.style == style)
    if condition:
        query = query.where(Hat.condition == condition)
    if status == "active":
        query = query.where(Hat.disposed_at.is_(None))
    elif status == "disposed":
        query = query.where(Hat.disposed_at.is_not(None))
    # status == "all" → no filter
    query = query.order_by(Hat.id).offset(offset).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_hat(db: AsyncSession, hat_id: int) -> Hat:
    result = await db.execute(
        select(Hat)
        .options(
            selectinload(Hat.case).selectinload(Case.room),
            selectinload(Hat.colors),
        )
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
    if update_data:
        await log_activity(
            db, kind="hat.updated", entity_type="hat", entity_id=hat_id,
            summary=f"Hat #{hat_id} updated",
            details={"fields": list(update_data.keys())},
        )
        await db.commit()
    return await _reload_hat(db, hat_id)


async def delete_hat(db: AsyncSession, hat_id: int) -> None:
    hat = await get_hat(db, hat_id)
    await db.delete(hat)
    await db.commit()
    await log_activity(
        db, kind="hat.deleted", entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} permanently deleted",
    )
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
    await log_activity(
        db, kind="hat.assigned", entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} {'assigned to case ' + str(case_id) if case_id else 'unassigned'}",
    )
    await db.commit()
    return await _reload_hat(db, hat_id)


async def dispose_hat(
    db: AsyncSession,
    hat_id: int,
    *,
    via: str,
    price: float | None = None,
    to: str | None = None,
    notes: str | None = None,
    disposed_at: datetime | None = None,
) -> Hat:
    if via not in DISPOSITION_VIAS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid disposal kind. Must be one of: {', '.join(sorted(DISPOSITION_VIAS))}",
        )
    hat = await get_hat(db, hat_id)
    hat.disposed_at = disposed_at or datetime.now(timezone.utc)
    hat.disposed_via = via
    hat.disposed_price = price
    hat.disposed_to = to
    hat.disposed_notes = notes
    # Free the case slot — disposed hats stay tied to their last case for
    # history but no longer count against capacity (see _validate_capacity).
    # We deliberately don't unassign so the case detail page can show
    # "previously held" hats if we want that later. Capacity check ignores
    # disposed hats already.
    await db.commit()
    await log_activity(
        db, kind="hat.disposed", entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} disposed via {via}" + (f" for ${price:.2f}" if price else ""),
        details={"via": via, "price": price, "to": to},
    )
    await db.commit()
    return await _reload_hat(db, hat_id)


async def undispose_hat(db: AsyncSession, hat_id: int) -> Hat:
    hat = await get_hat(db, hat_id)
    if hat.disposed_at is None:
        return hat
    # If the original case is still around AND has space, the hat returns
    # there. Otherwise it becomes unassigned.
    target_case_id = hat.case_id
    hat.disposed_at = None
    hat.disposed_via = None
    hat.disposed_price = None
    hat.disposed_to = None
    hat.disposed_notes = None
    if target_case_id is not None:
        try:
            await _validate_capacity(db, target_case_id, hat.is_beanie, exclude_hat_id=hat.id)
        except HTTPException:
            hat.case_id = None
            hat.position_in_case = None
    await db.commit()
    await log_activity(
        db, kind="hat.undisposed", entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} restored from disposed state",
    )
    await db.commit()
    return await _reload_hat(db, hat_id)
