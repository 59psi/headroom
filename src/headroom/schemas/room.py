from datetime import datetime

from pydantic import BaseModel

from headroom.schemas.common import OptionalRoomName, RoomName

from headroom.schemas.case import CaseRead
from headroom.schemas.hat import HatRead


class RoomCreate(BaseModel):
    name: RoomName


class RoomUpdate(BaseModel):
    name: OptionalRoomName = None


class RoomRead(BaseModel):
    id: int
    name: str
    case_count: int
    #: Hats kept in this room with no case. They have nowhere else to be seen —
    #: a cased hat is reachable through its case, a hat on a shelf is not.
    loose_hat_count: int = 0
    # Exactly one room is the default: the fallback for orphaned cases and the
    # room new cases land in. It's the only room that can't be deleted.
    is_default: bool = False
    created_at: datetime
    updated_at: datetime


class RoomDetail(RoomRead):
    """A room and what is actually in it.

    `loose_hats` first, deliberately — see `room_service.get_room_contents`.
    """

    loose_hats: list[HatRead] = []
    cases: list[CaseRead] = []
