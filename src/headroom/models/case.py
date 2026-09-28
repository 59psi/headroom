from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, event, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from headroom.database import Base, UtcDateTime


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_type: Mapped[str] = mapped_column(String(12))  # "archive" or "daily_wear"
    sequence_number: Mapped[int] = mapped_column(Integer)
    display_id: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Per-case hat capacity override; NULL → type default (`capacity.MAX_REGULAR`
    # / `capacity.MAX_BEANIE` — never restated here; the beanie figure has moved
    # twice). Those are the NOMINAL figures — a regular case additionally accepts
    # one more as `overfull`, which is a different number and not this one.
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # REQUIRED, with no default. This carried `default=1` — the hardcoded room
    # the `Room.is_default` flag was introduced to replace — so a `Case(...)`
    # that forgot its room landed in room 1 silently, and room 1 is allowed to
    # have been deleted. The caller resolves the room
    # (`room_service.get_default_room_id` when none is named), and
    # `_require_room` below makes forgetting an error on every install: an
    # upgraded database's column is nullable (SQLite cannot ADD a NOT NULL
    # column without a default), so the schema alone would not say so.
    room_id: Mapped[int] = mapped_column(Integer, ForeignKey("rooms.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, server_default=func.now(), onupdate=func.now()
    )

    # `lazy="raise"`, like `Room.cases`, and for the same reason. As a selectin
    # collection it made every Case load carry every hat in it (disposed ones
    # included) with their colors — so `get_room`, which loads a room's cases
    # only to count them, pulled the room's entire contents. The queries that
    # want a case's hats say so with `selectinload(Case.hats)`.
    hats: Mapped[list["Hat"]] = relationship(  # noqa: F821
        back_populates="case", lazy="raise"
    )
    # Many-to-one, so selectin here costs one row per case and cascades no
    # further now that `Room.cases` is "raise" (it was already a cycle back
    # to Case, which a default eager chain does not follow).
    room: Mapped["Room"] = relationship(  # noqa: F821
        back_populates="cases", lazy="selectin"
    )


@event.listens_for(Case, "before_insert")
@event.listens_for(Case, "before_update")
def _require_room(_mapper, _connection, target: Case) -> None:
    """Refuse to write a case that is in no room.

    Runs after the unit of work has copied a `case.room = room` assignment
    into `room_id`, so either way of naming the room satisfies it.
    """
    if target.room_id is None:
        raise ValueError(
            f"Case {target.display_id!r} has no room_id; resolve one "
            "(room_service.get_default_room_id) before saving it"
        )
