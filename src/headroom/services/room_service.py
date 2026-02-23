from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.case import Case
from headroom.models.room import Room
from headroom.schemas.room import RoomCreate, RoomUpdate


async def _reload_room(db: AsyncSession, room_id: int) -> Room:
    db.expire_all()
    result = await db.execute(
        select(Room)
        .options(selectinload(Room.cases))
        .where(Room.id == room_id)
    )
    return result.scalar_one()


async def list_rooms(db: AsyncSession) -> list[Room]:
    result = await db.execute(
        select(Room).options(selectinload(Room.cases)).order_by(Room.name)
    )
    return list(result.scalars().all())


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
    return await _reload_room(db, room.id)


async def update_room(
    db: AsyncSession, room_id: int, data: RoomUpdate
) -> Room:
    room = await get_room(db, room_id)
    if data.name is not None:
        room.name = data.name
    await db.commit()
    return await _reload_room(db, room.id)


async def delete_room(db: AsyncSession, room_id: int) -> None:
    if room_id == 1:
        raise HTTPException(
            status_code=400, detail="Cannot delete the default room"
        )
    room = await get_room(db, room_id)
    # Reassign cases to default room via bulk update to avoid cascade issues
    await db.execute(
        update(Case).where(Case.room_id == room_id).values(room_id=1)
    )
    await db.flush()
    # Expire to clear stale relationship data before delete
    db.expire_all()
    room = await db.get(Room, room_id)
    await db.delete(room)
    await db.commit()
