from datetime import datetime

from sqlalchemy import Boolean, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from headroom.database import Base, UtcDateTime


class Room(Base):
    __tablename__ = "rooms"
    # AUTOINCREMENT, so a deleted room's id is never handed to a new one (a
    # bookmarked `/rooms/7` must not quietly open a different room). Every
    # existing install already has it: `rooms` used to be CREATEd by hand in
    # `database._run_migrations` with exactly this keyword, and declaring it
    # here is what lets `create_all` own fresh installs without the two
    # disagreeing.
    __table_args__ = {"sqlite_autoincrement": True}

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

    # `lazy="raise"`: a room's cases are loaded only where a query asks for
    # them with `selectinload(Room.cases)`; touched anywhere else they fail
    # loudly instead of quietly loading. (A flush that deletes a room still
    # loads them — the unit of work is exempt from "raise" — so `db.delete`
    # keeps working without an option.)
    #
    # This was `lazy="selectin"`, and that is not a per-room cost. Every Room
    # load — `list_rooms`, `get_room`, and every loose hat through
    # `Hat.direct_room` — pulled all of the room's cases, which (while
    # `Case.hats` was selectin too) pulled every hat in them with its colors
    # and wear log. Measured on 40 cases and 160 hats: `list_rooms` issued
    # five statements and left 681 objects in the session to produce one
    # COUNT, and reading a single loose hat by id loaded its room's 40 cases.
    # The 2.7.0 "fix" swapped the call site's `selectinload` for a COUNT and
    # changed nothing, because the mapper default did the loading. (A cased
    # hat escaped only because SQLAlchemy stops a default eager chain at the
    # first mapper it revisits: Hat -> Case -> Room -> Case is a cycle.)
    cases: Mapped[list["Case"]] = relationship(  # noqa: F821
        back_populates="room", lazy="raise"
    )
