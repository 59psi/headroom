from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.case import Case
from headroom.schemas.case import CaseCreate, CaseType, CaseUpdate
from headroom.services import capacity as capacity_rules, room_service
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
    # `get_next_sequence` is read-then-write like every placement decision:
    # six concurrent creates used to be one case and five 500s on the unique
    # `display_id`. Serialized under the shelf-wide lock instead.
    async with capacity_rules.placement_lock():
        return await _create_case_locked(db, data)


async def _create_case_locked(db: AsyncSession, data: CaseCreate) -> Case:
    seq = await get_next_sequence(db, data.case_type)
    display_id = _make_display_id(data.case_type, seq)
    room_id = data.room_id
    if room_id is None:
        room_id = await room_service.get_default_room_id(db)
    elif not await room_service.room_exists(db, room_id):
        # Defense in depth behind the frontend fix. Nothing enforces this at the
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
    # Omitted vs explicit null. `if data.capacity is not None` treated both as
    # "leave it", so clearing the box in the Edit form — whose empty placeholder
    # promises the type default — changed nothing: a per-case override could be
    # set and never removed. A field the client SENT as null is a clear.
    if "capacity" in data.model_fields_set:
        case.capacity = data.capacity
    await db.commit()
    return await _reload_case(db, case.id)


async def delete_case(db: AsyncSession, display_id: str) -> None:
    case = await get_case_by_display_id(db, display_id)
    # Detach every hat before deleting, keeping it IN THE ROOM the case was in.
    # Since 2.33 a hat can live in a room with no case, so "unassigned" and
    # "not in any room" stopped being the same state — clearing `case_id` alone
    # left these hats reachable from nowhere but the Hats list and search, which
    # reads as the shelf emptying itself. `room_service.delete_room` states the
    # same principle for the symmetric operation. The hats did not physically
    # move; only their container went.
    #
    # The room is VALIDATED first. This is the one place that wrote a room id
    # without checking, and `create_case` below documents why that matters:
    # nothing enforces it at the DB level, so a case orphaned by an older
    # version would hand every one of its hats a dangling `direct_room_id` —
    # `Hat.room` then resolves to None and the hat is in no room while the
    # column insists otherwise. Falling back to the default room keeps them
    # somewhere a person can actually find them.
    room_id = case.room_id
    if not await room_service.room_exists(db, room_id):
        room_id = await room_service.get_default_room_id(db)

    # `Case.hats` is unfiltered, so it includes DISPOSED hats. They keep their
    # disposition and must not be filed onto a shelf they are not on — and they
    # must not be counted in the audit line either, which is what made "N
    # hat(s) unassigned" wrong in both halves.
    active = [h for h in case.hats if h.disposed_at is None]
    for hat in active:
        hat.detach_from_case(room_id)
    for hat in case.hats:
        if hat.disposed_at is not None:
            # `None`, deliberately: a disposed hat is not filed onto a shelf it
            # is not on. Same writer as the active hats above — the model's.
            hat.detach_from_case(None)
    case_id = case.id
    await db.delete(case)
    await db.commit()
    await log_and_commit(
        db, kind="case.deleted", entity_type="case", entity_id=case_id,
        # "moved to", not "unassigned" — the durable record has to name what
        # actually happened, and since 2.57.1 the hats keep their room.
        summary=f"Case {display_id} deleted · {len(active)} hat(s) moved to the room",
    )
