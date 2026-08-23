from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.models.room import Room
from headroom.schemas.room import RoomCreate, RoomUpdate
from headroom.services.activity_service import log_and_commit


async def _reload_room(db: AsyncSession, room_id: int) -> Room:
    db.expire_all()
    result = await db.execute(
        select(Room)
        .options(selectinload(Room.cases))
        .where(Room.id == room_id)
    )
    return result.scalar_one()


async def list_rooms(db: AsyncSession) -> list[tuple[Room, int]]:
    """Every room paired with its case count, without loading the cases.

    `selectinload(Room.cases)` reads harmlessly — the caller only wants
    `len(room.cases)` — but `Case.hats`, `Hat.colors` and `Hat.wear_logs` are
    all `lazy="selectin"` at the mapper, so pulling the cases cascades into
    every hat, colour and wear-log row in the whole collection to produce a
    number. The cost scaled with the size of the collection rather than the
    number of rooms (~30ms vs ~0.3ms at 300 hats, and a Pi is several times
    slower). One grouped COUNT gives the same answer.
    """
    counts = (
        select(Case.room_id.label("room_id"), func.count(Case.id).label("n"))
        .group_by(Case.room_id)
        .subquery()
    )
    result = await db.execute(
        select(Room, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.room_id == Room.id)
        .order_by(Room.name)
    )
    return [(room, int(n)) for room, n in result.all()]


async def get_room(db: AsyncSession, room_id: int) -> Room:
    result = await db.execute(
        select(Room)
        .options(selectinload(Room.cases))
        .where(Room.id == room_id)
    )
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


async def create_room(db: AsyncSession, data: RoomCreate) -> Room:
    room = Room(name=data.name)
    db.add(room)
    await db.commit()
    await log_and_commit(
        db, kind="room.created", entity_type="room", entity_id=room.id,
        summary=f"Room '{room.name}' created",
    )
    return await _reload_room(db, room.id)


async def update_room(
    db: AsyncSession, room_id: int, data: RoomUpdate
) -> Room:
    room = await get_room(db, room_id)
    if data.name is not None:
        room.name = data.name
    await db.commit()
    return await _reload_room(db, room.id)


async def room_exists(db: AsyncSession, room_id: int) -> bool:
    """Cheap existence check — no relationship loads."""
    result = await db.execute(select(Room.id).where(Room.id == room_id).limit(1))
    return result.scalar_one_or_none() is not None


async def get_default_room_id(db: AsyncSession) -> int:
    """Id of the room currently flagged `is_default`.

    Falls back to the lowest room id if nothing is flagged, so a database that
    somehow lost the flag still creates cases instead of 500ing. `init_db` calls
    `ensure_default_room()` on boot, so this fallback should never fire.
    """
    result = await db.execute(
        select(Room.id).where(Room.is_default.is_(True)).order_by(Room.id).limit(1)
    )
    room_id = result.scalar_one_or_none()
    if room_id is not None:
        return room_id
    result = await db.execute(select(Room.id).order_by(Room.id).limit(1))
    fallback = result.scalar_one_or_none()
    if fallback is None:
        raise HTTPException(status_code=400, detail="No rooms exist")
    return fallback


async def set_default_room(db: AsyncSession, room_id: int) -> Room:
    """Move the default flag to `room_id`. Clearing first keeps it single."""
    room = await get_room(db, room_id)
    await db.execute(update(Room).where(Room.is_default.is_(True)).values(is_default=False))
    await db.execute(update(Room).where(Room.id == room.id).values(is_default=True))
    await db.commit()
    await log_and_commit(
        db, kind="room.default_changed", entity_type="room", entity_id=room.id,
        summary=f"Room '{room.name}' is now the default",
    )
    return await _reload_room(db, room.id)


async def delete_room(db: AsyncSession, room_id: int) -> None:
    room = await get_room(db, room_id)
    # The default room is the target orphaned cases get reassigned to, so it
    # can't be the thing being deleted. Designating another room first is what
    # unblocks this — no longer "id 1 is special forever".
    if room.is_default:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot delete the default room — make another room the default "
                "first, then delete this one."
            ),
        )
    name = room.name
    fallback_id = await get_default_room_id(db)
    moved = (
        await db.execute(
            select(func.count(Case.id)).where(Case.room_id == room_id)
        )
    ).scalar() or 0
    moved_hats = (
        await db.execute(
            select(func.count(Hat.id)).where(Hat.direct_room_id == room_id)
        )
    ).scalar() or 0
    # Reassign cases to the default room via bulk update to avoid cascade issues
    await db.execute(
        update(Case).where(Case.room_id == room_id).values(room_id=fallback_id)
    )
    # Hats kept in this room with NO case move too. They are not reachable via
    # any case, so the case sweep above misses them entirely — and left behind
    # they would point at a deleted room, which reads as the hat vanishing from
    # every room view while still existing.
    await db.execute(
        update(Hat)
        .where(Hat.direct_room_id == room_id)
        .values(direct_room_id=fallback_id)
    )
    await db.flush()
    # Expire to clear stale relationship data before delete
    db.expire_all()
    room = await db.get(Room, room_id)
    await db.delete(room)
    await db.commit()
    await log_and_commit(
        db, kind="room.deleted", entity_type="room", entity_id=room_id,
        summary=(
            f"Room '{name}' deleted · {moved} case(s) and {moved_hats} "
            f"caseless hat(s) moved to the default room"
        ),
    )
