"""Colorway catalog + purchase history.

The catalog is harvested from melinrecap listing titles ("Model - Colorway")
— years of sold-out drops that no longer exist on melin.com. Purchases come
from order-confirmation emails (imported as structured line items) and give
hats a real cost basis.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from headroom.database import Base


class ColorwayEntry(Base):
    __tablename__ = "colorway_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    model_name: Mapped[str] = mapped_column(String(120), index=True)
    colorway: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    listing_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Purchase(Base):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(20), default="email")  # email | manual
    order_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    order_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    item_title: Mapped[str] = mapped_column(String(200))
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    colorway: Mapped[str | None] = mapped_column(String(120), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The hat this purchase was matched to, if any. The constraint existed at
    # the schema level with no ORM relationship, so every caller that wanted
    # the hat had to issue its own `db.get(Hat, purchase.hat_id)` — the exact
    # by-hand navigation the mapper is for.
    hat_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hats.id"), nullable=True, index=True
    )
    # `lazy="selectin"` to match the rest of this codebase's async loading
    # rules: a lazy="select" access on an AsyncSession raises rather than
    # emitting a query, so a plain attribute read would be a runtime error.
    hat: Mapped["Hat | None"] = relationship(lazy="selectin")  # noqa: F821
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
