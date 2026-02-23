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
    created_at: datetime
    updated_at: datetime
