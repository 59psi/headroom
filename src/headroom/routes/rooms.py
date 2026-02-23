from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.room import RoomCreate, RoomRead, RoomUpdate
from headroom.services import room_service

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


def _room_to_read(room) -> RoomRead:
    return RoomRead(
        id=room.id,
        name=room.name,
        case_count=len(room.cases) if room.cases else 0,
        created_at=room.created_at,
        updated_at=room.updated_at,
    )


@router.post("", response_model=RoomRead, status_code=201)
async def create_room(data: RoomCreate, db: AsyncSession = Depends(get_db)):
    room = await room_service.create_room(db, data)
    return _room_to_read(room)


@router.get("", response_model=list[RoomRead])
async def list_rooms(db: AsyncSession = Depends(get_db)):
    rooms = await room_service.list_rooms(db)
    return [_room_to_read(r) for r in rooms]


@router.get("/{room_id}", response_model=RoomRead)
async def get_room(room_id: int, db: AsyncSession = Depends(get_db)):
    room = await room_service.get_room(db, room_id)
    return _room_to_read(room)


@router.put("/{room_id}", response_model=RoomRead)
async def update_room(
    room_id: int, data: RoomUpdate, db: AsyncSession = Depends(get_db)
):
    room = await room_service.update_room(db, room_id, data)
    return _room_to_read(room)


@router.delete("/{room_id}", status_code=204)
async def delete_room(room_id: int, db: AsyncSession = Depends(get_db)):
    await room_service.delete_room(db, room_id)
