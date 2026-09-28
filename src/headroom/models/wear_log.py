"""Wear log: one row per time a hat is worn (the 'wearing this today' tap).

Unlocks wear counts, cost-per-wear (against purchase price or retail
estimate), and neglected-hat surfacing. `hats.date_last_worn` stays the
denormalized quick answer; this table is the history behind it.
"""

from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from headroom.database import Base, UtcDateTime


class WearLog(Base):
    __tablename__ = "wear_log"

    # One wear per hat per day: the "wearing this today" tap is idempotent, but
    # the app-level check is read-then-write, so two rapid taps can both pass it.
    # This constraint makes the second insert fail cleanly instead of duplicating.
    __table_args__ = (UniqueConstraint("hat_id", "worn_at", name="uq_wear_hat_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hat_id: Mapped[int] = mapped_column(Integer, ForeignKey("hats.id"), index=True)
    worn_at: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, server_default=func.now())
    #: What `hats.date_last_worn` held when this wear was logged — the date an
    #: undo of THIS wear hands back. The wear log alone cannot answer that:
    #: `date_last_worn` is also typed by hand, and a hand-typed date has no
    #: wear row behind it, so an undo that fell back to "the previous wear"
    #: erased it. On the row, not in the activity log where it was first kept:
    #: that log is pruned by age (`HEADROOM_ACTIVITY_LOG_RETENTION_DAYS`), and
    #: an undo must not stop working once the audit trail of the tap expires.
    #: NULL for wears logged before this column existed, which undo as before.
    date_last_worn_before: Mapped[date | None] = mapped_column(Date, nullable=True)
