from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from headroom.database import Base


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_type: Mapped[str] = mapped_column(String(12))  # "archive" or "daily_wear"
    sequence_number: Mapped[int] = mapped_column(Integer)
    display_id: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    room_id: Mapped[int] = mapped_column(Integer, ForeignKey("rooms.id"), default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    hats: Mapped[list["Hat"]] = relationship(  # noqa: F821
        back_populates="case", lazy="selectin"
    )
    room: Mapped["Room"] = relationship(  # noqa: F821
        back_populates="cases", lazy="selectin"
    )
