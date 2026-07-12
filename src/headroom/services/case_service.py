from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.case import Case
from headroom.schemas.case import CaseCreate, CaseType, CaseUpdate


async def _reload_case(db: AsyncSession, case_id: int) -> Case:
    db.expire_all()
    result = await db.execute(
        select(Case)
        .options(selectinload(Case.hats), selectinload(Case.room))
        .where(Case.id == case_id)
    )
    return result.scalar_one()


def _make_display_id(case_type: CaseType, seq: int) -> str:
    prefix = "A" if case_type == CaseType.archive else "D"
    return f"{prefix}-{seq:03d}"


async def get_next_sequence(db: AsyncSession, case_type: CaseType) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(Case.sequence_number), 0)).where(
            Case.case_type == case_type
        )
    )
    return result.scalar_one() + 1


async def create_case(db: AsyncSession, data: CaseCreate) -> Case:
    seq = await get_next_sequence(db, data.case_type)
    display_id = _make_display_id(data.case_type, seq)
    case = Case(
        case_type=data.case_type,
        sequence_number=seq,
        display_id=display_id,
        room_id=data.room_id,
        capacity=data.capacity,
    )
    db.add(case)
    await db.commit()
    return await _reload_case(db, case.id)


async def list_cases(db: AsyncSession) -> list[Case]:
    result = await db.execute(
        select(Case)
        .options(selectinload(Case.hats), selectinload(Case.room))
        .order_by(Case.display_id)
    )
    return list(result.scalars().all())


async def get_case_by_display_id(db: AsyncSession, display_id: str) -> Case:
    result = await db.execute(
        select(Case)
        .options(selectinload(Case.hats), selectinload(Case.room))
        .where(Case.display_id == display_id.upper())
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


async def update_case(
    db: AsyncSession, display_id: str, data: CaseUpdate
) -> Case:
    case = await get_case_by_display_id(db, display_id)
    if data.case_type is not None and data.case_type != case.case_type:
        seq = await get_next_sequence(db, data.case_type)
        case.case_type = data.case_type
        case.sequence_number = seq
        case.display_id = _make_display_id(data.case_type, seq)
    if data.room_id is not None:
        case.room_id = data.room_id
    if data.capacity is not None:
        case.capacity = data.capacity
    await db.commit()
    return await _reload_case(db, case.id)


async def delete_case(db: AsyncSession, display_id: str) -> None:
    case = await get_case_by_display_id(db, display_id)
    # Unassign all hats before deleting
    for hat in list(case.hats):
        hat.case_id = None
        hat.position_in_case = None
    await db.delete(case)
    await db.commit()
