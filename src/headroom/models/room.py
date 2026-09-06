from datetime import datetime

from sqlalchemy import Boolean, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from headroom.database import Base, UtcDateTime


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    # Exactly one room carries this flag. It is the fallback that orphaned cases
    # land in when their room is deleted, and the room new cases go to when the
    # caller doesn't name one. Deliberately a flag rather than a hardcoded id=1
    # so any room can hold the role and the original can be deleted once another
    # takes over. `database.ensure_default_room()` repairs the invariant on boot.
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, server_default=func.now(), onupdate=func.now()
    )

    cases: Mapped[list["Case"]] = relationship(  # noqa: F821
        back_populates="room", lazy="selectin"
    )
