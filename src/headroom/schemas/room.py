from datetime import datetime

from pydantic import BaseModel


class RoomCreate(BaseModel):
    name: str


class RoomUpdate(BaseModel):
    name: str | None = None


class RoomRead(BaseModel):
    id: int
    name: str
    case_count: int
    # Exactly one room is the default: the fallback for orphaned cases and the
    # room new cases land in. It's the only room that can't be deleted.
    is_default: bool = False
    created_at: datetime
    updated_at: datetime
