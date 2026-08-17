from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.case import Case
from headroom.schemas.case import CaseCreate, CaseType, CaseUpdate
from headroom.services import room_service
from headroom.services.activity_service import log_and_commit


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
    room_id = data.room_id
    if room_id is None:
        room_id = await room_service.get_default_room_id(db)
    elif not await room_service.room_exists(db, room_id):
        # Defence in depth behind the frontend fix. Nothing enforces this at the
        # DB level (no `PRAGMA foreign_keys`), so an id for a room that isn't
        # there used to be written straight through — and the symptoms never
        # named the cause: the case reported its room as "Unknown", and the room
        # it should have been in reported zero cases.
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found")
    case = Case(
        case_type=data.case_type,
        sequence_number=seq,
        display_id=display_id,
        room_id=room_id,
        capacity=data.capacity,
    )
    db.add(case)
    await db.commit()
    await log_and_commit(
        db, kind="case.created", entity_type="case", entity_id=case.id,
        summary=f"Case {display_id} created in room {room_id}",
    )
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
        # Validated for the same reason as on create: nothing below this layer
        # enforces it, so an id for a missing room would orphan the case — and
        # this is the path used to *repair* an orphan, which makes silently
        # writing another bad id the worst possible failure here.
        if not await room_service.room_exists(db, data.room_id):
            raise HTTPException(status_code=404, detail=f"Room {data.room_id} not found")
        case.room_id = data.room_id
    if data.capacity is not None:
        case.capacity = data.capacity
    await db.commit()
    return await _reload_case(db, case.id)


async def delete_case(db: AsyncSession, display_id: str) -> None:
    case = await get_case_by_display_id(db, display_id)
    # Unassign all hats before deleting
    freed = len(case.hats)
    for hat in list(case.hats):
        hat.case_id = None
        hat.position_in_case = None
    case_id = case.id
    await db.delete(case)
    await db.commit()
    await log_and_commit(
        db, kind="case.deleted", entity_type="case", entity_id=case_id,
        summary=f"Case {display_id} deleted · {freed} hat(s) unassigned",
    )
