from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.routes._api import DomainErrorRoute
from headroom.schemas.hat import HatRead
from headroom.schemas.room import RoomCreate, RoomDetail, RoomRead, RoomUpdate
from headroom.services import case_service, room_service

router = APIRouter(prefix="/api/rooms", tags=["rooms"], route_class=DomainErrorRoute)


@router.post("", response_model=RoomRead, status_code=201)
async def create_room(data: RoomCreate, db: AsyncSession = Depends(get_db)):
    room = await room_service.create_room(db, data)
    return await room_service.room_read(db, room)


@router.get("", response_model=list[RoomRead])
async def list_rooms(db: AsyncSession = Depends(get_db)):
    return await room_service.list_room_reads(db)


@router.get("/{room_id}", response_model=RoomDetail)
async def get_room(room_id: int, db: AsyncSession = Depends(get_db)):
    """A room and what is in it — loose hats first, then its cases.

    Loose hats lead because they are the half of a room with nowhere else to
    be seen: a cased hat is reachable through its case from the Cases tab, a
    hat on a shelf is only ever visible here and in search.
    """
    room, loose, cases = await room_service.get_room_contents(db, room_id)
    base = room_service.to_read(room, case_count=len(cases), loose_hat_count=len(loose))
    return RoomDetail(
        **base.model_dump(),
        loose_hats=[HatRead.model_validate(h) for h in loose],
        cases=[case_service.case_read(c) for c in cases],
    )


@router.put("/{room_id}", response_model=RoomRead)
async def update_room(
    room_id: int, data: RoomUpdate, db: AsyncSession = Depends(get_db)
):
    room = await room_service.update_room(db, room_id, data)
    return await room_service.room_read(db, room)


@router.post("/{room_id}/default", response_model=RoomRead)
async def make_default_room(room_id: int, db: AsyncSession = Depends(get_db)):
    """Move the default flag to this room, freeing the previous one for deletion."""
    room = await room_service.set_default_room(db, room_id)
    return await room_service.room_read(db, room)


@router.delete("/{room_id}", status_code=204)
async def delete_room(room_id: int, db: AsyncSession = Depends(get_db)):
    await room_service.delete_room(db, room_id)
