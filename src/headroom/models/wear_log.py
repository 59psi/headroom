"""Wear log: one row per time a hat is worn (the 'wearing this today' tap).

Unlocks wear counts, cost-per-wear (against purchase price or retail
estimate), and neglected-hat surfacing. `hats.date_last_worn` stays the
denormalized quick answer; this table is the history behind it.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from headroom.database import Base


class WearLog(Base):
    __tablename__ = "wear_log"

    # One wear per hat per day: the "wearing this today" tap is idempotent, but
    # the app-level check is read-then-write, so two rapid taps can both pass it.
    # This constraint makes the second insert fail cleanly instead of duplicating.
    __table_args__ = (UniqueConstraint("hat_id", "worn_at", name="uq_wear_hat_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hat_id: Mapped[int] = mapped_column(Integer, ForeignKey("hats.id"), index=True)
    worn_at: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
