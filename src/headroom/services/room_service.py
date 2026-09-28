from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.models.room import Room
from headroom.schemas.room import RoomCreate, RoomRead, RoomUpdate
from headroom.services import activity_service, errors, hat_service


def to_read(room: Room, *, case_count: int, loose_hat_count: int) -> RoomRead:
    """Room → `RoomRead`, with both counts REQUIRED.

    The list route counts every room in two grouped queries; a single room is
    counted by `room_read`. There is no third way — the mapper used to default
    the loose count to 0, and the rename and set-default routes shipped that.
    """
    return RoomRead(
        id=room.id,
        name=room.name,
        case_count=case_count,
        loose_hat_count=loose_hat_count,
        is_default=bool(room.is_default),
        created_at=room.created_at,
        updated_at=room.updated_at,
    )


async def room_read(db: AsyncSession, room: Room) -> RoomRead:
    """One room's `RoomRead`, counted now."""
    case_count, loose = await room_counts(db, room.id)
    return to_read(room, case_count=case_count, loose_hat_count=loose)


async def list_room_reads(db: AsyncSession) -> list[RoomRead]:
    """Every room's `RoomRead`, in two grouped COUNTs rather than one per room."""
    loose = await loose_hat_counts(db)
    return [
        to_read(room, case_count=n, loose_hat_count=loose.get(room.id, 0))
        for room, n in await list_rooms(db)
    ]


async def _reload_room(db: AsyncSession, room_id: int) -> Room:
    # The room row alone: every count a `RoomRead` reports comes from
    # `room_counts`, so nothing here needs its cases loaded.
    db.expire_all()
    result = await db.execute(select(Room).where(Room.id == room_id))
    return result.scalar_one()


async def list_rooms(db: AsyncSession) -> list[tuple[Room, int]]:
    """Every room paired with its case count, without loading the cases.

    `Room.cases` and `Case.hats` are `lazy="raise"` now, so loading rooms
    loads rooms — nothing cascades into cases, hats, colors or wear logs the
    way the old selectin chain did (~30ms vs ~0.3ms at 300 hats). A number is
    still all the caller wants, and one grouped COUNT is the right way to get
    it; `Hat.wear_count` is itself a SQL count, not a loaded collection.
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
    # The room row alone, like `_reload_room`. It used to `selectinload` the
    # room's cases, which no caller reads — `RoomRead`'s counts come from
    # `room_counts`, and deleting a room reassigns its cases with a bulk
    # UPDATE (the flush that deletes the row loads the collection itself).
    result = await db.execute(select(Room).where(Room.id == room_id))
    room = result.scalar_one_or_none()
    if not room:
        raise errors.NotFound("Room not found")
    return room


async def room_counts(db: AsyncSession, room_id: int) -> tuple[int, int]:
    """(cases in the room, active hats kept in it with no case).

    What `RoomRead` reports, counted in SQL for one room — the single-room
    twin of `list_rooms` + `loose_hat_counts`. Every route that answers with a
    `RoomRead` asks this; the rename and set-default routes used to fall back
    to a parameter default and reported `loose_hat_count: 0` for a room with
    hats on its shelf.
    """
    cases = (
        await db.execute(select(func.count(Case.id)).where(Case.room_id == room_id))
    ).scalar() or 0
    loose = (
        await db.execute(
            select(func.count(Hat.id)).where(
                Hat.direct_room_id == room_id, Hat.disposed_at.is_(None)
            )
        )
    ).scalar() or 0
    return int(cases), int(loose)


async def create_room(db: AsyncSession, data: RoomCreate) -> Room:
    room = Room(name=data.name)
    db.add(room)
    await db.commit()
    await activity_service.log_and_commit(
        db, kind="room.created", entity_type="room", entity_id=room.id,
        summary=f"Room '{room.name}' created",
    )
    return await _reload_room(db, room.id)


async def update_room(
    db: AsyncSession, room_id: int, data: RoomUpdate
) -> Room:
    room = await get_room(db, room_id)
    previous = room.name
    if data.name is not None:
        room.name = data.name
    await db.commit()
    if room.name != previous:
        # Audited like create and delete: a rename is what a room is known by
        # on every case label and list, and it left no trace.
        await activity_service.log_and_commit(
            db, kind="room.renamed", entity_type="room", entity_id=room_id,
            summary=f"Room '{previous}' renamed to '{room.name}'",
            details={"previous": previous},
        )
    return await _reload_room(db, room_id)


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
        raise errors.Invalid("No rooms exist")
    return fallback


async def set_default_room(db: AsyncSession, room_id: int) -> Room:
    """Move the default flag to `room_id`. Clearing first keeps it single."""
    room = await get_room(db, room_id)
    await db.execute(update(Room).where(Room.is_default.is_(True)).values(is_default=False))
    await db.execute(update(Room).where(Room.id == room.id).values(is_default=True))
    await db.commit()
    await activity_service.log_and_commit(
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
        raise errors.Invalid(
            "Cannot delete the default room — make another room the default "
            "first, then delete this one."
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
    await activity_service.log_and_commit(
        db, kind="room.deleted", entity_type="room", entity_id=room_id,
        summary=(
            f"Room '{name}' deleted · {moved} case(s) and {moved_hats} "
            f"caseless hat(s) moved to the default room"
        ),
    )


async def get_room_contents(db: AsyncSession, room_id: int) -> tuple[Room, list[Hat], list[Case]]:
    """A room, the hats kept loose in it, and its cases.

    Loose hats come back as their own list rather than mixed in with the cases'
    contents, because they are the half of a room that has nowhere else to be
    seen: a cased hat is reachable through its case from the Cases tab, but a
    hat on a shelf is only ever visible here and in search.

    Ordered newest-first — a hat set down loose is usually one you have just
    handled, and the room view is where you go to find it again.
    """
    room = await get_room(db, room_id)

    loose = (
        await db.execute(
            select(Hat)
            .options(
                *hat_service.hat_loads(),
            )
            .where(Hat.direct_room_id == room_id, Hat.disposed_at.is_(None))
            .order_by(Hat.created_at.desc(), Hat.id.desc())
        )
    ).scalars().all()

    cases = (
        await db.execute(
            select(Case)
            .options(selectinload(Case.room), selectinload(Case.hats))
            .where(Case.room_id == room_id)
            .order_by(Case.display_id)
        )
    ).scalars().all()

    return room, list(loose), list(cases)


async def loose_hat_counts(db: AsyncSession) -> dict[int, int]:
    """Loose-hat count per room, for the rooms list.

    One grouped COUNT rather than loading hats per room, for the same reason
    `list_rooms` counts cases in SQL: pulling the rows (and each hat's colors)
    for the whole collection to produce a number is the wrong trade.
    """
    rows = await db.execute(
        select(Hat.direct_room_id, func.count(Hat.id))
        .where(Hat.direct_room_id.is_not(None), Hat.disposed_at.is_(None))
        .group_by(Hat.direct_room_id)
    )
    return {room_id: int(n) for room_id, n in rows.all()}
