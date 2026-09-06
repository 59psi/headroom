from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.routes.cases import case_to_read
from headroom.routes.hats import hat_to_read
from headroom.schemas.room import RoomCreate, RoomDetail, RoomRead, RoomUpdate
from headroom.services import room_service

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


def _room_to_read(room, case_count: int | None = None, loose_hat_count: int = 0) -> RoomRead:
    """`case_count` is passed in by the list route, which counts in SQL rather
    than loading the cases (and, through them, the entire collection)."""
    return RoomRead(
        id=room.id,
        name=room.name,
        case_count=case_count if case_count is not None else (len(room.cases) if room.cases else 0),
        loose_hat_count=loose_hat_count,
        is_default=bool(room.is_default),
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
    loose = await room_service.loose_hat_counts(db)
    return [_room_to_read(r, n, loose.get(r.id, 0)) for r, n in rooms]


@router.get("/{room_id}", response_model=RoomDetail)
async def get_room(room_id: int, db: AsyncSession = Depends(get_db)):
    """A room and what is in it — loose hats first, then its cases.

    Loose hats lead because they are the half of a room with nowhere else to
    be seen: a cased hat is reachable through its case from the Cases tab, a
    hat on a shelf is only ever visible here and in search.
    """
    room, loose, cases = await room_service.get_room_contents(db, room_id)
    base = _room_to_read(room, len(cases), len(loose))
    return RoomDetail(
        **base.model_dump(),
        loose_hats=[hat_to_read(h) for h in loose],
        cases=[case_to_read(c) for c in cases],
    )


@router.put("/{room_id}", response_model=RoomRead)
async def update_room(
    room_id: int, data: RoomUpdate, db: AsyncSession = Depends(get_db)
):
    room = await room_service.update_room(db, room_id, data)
    return _room_to_read(room)


@router.post("/{room_id}/default", response_model=RoomRead)
async def make_default_room(room_id: int, db: AsyncSession = Depends(get_db)):
    """Move the default flag to this room, freeing the previous one for deletion."""
    room = await room_service.set_default_room(db, room_id)
    return _room_to_read(room)


@router.delete("/{room_id}", status_code=204)
async def delete_room(room_id: int, db: AsyncSession = Depends(get_db)):
    await room_service.delete_room(db, room_id)
