from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from headroom.database import Base


class Hat(Base):
    __tablename__ = "hats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cases.id"), nullable=True
    )
    position_in_case: Mapped[int | None] = mapped_column(Integer, nullable=True)
    photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    condition: Mapped[str] = mapped_column(String(20))  # new_with_tags, new, worn
    date_last_worn: Mapped[date | None] = mapped_column(Date, nullable=True)
    size: Mapped[str] = mapped_column(String(10))  # small, classic, x_large
    style: Mapped[str] = mapped_column(String(20))
    custom_style_detail: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    is_beanie: Mapped[bool] = mapped_column(Boolean, default=False)

    # AI-detected attributes
    brand: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model_confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)  # high/medium/low
    style_descriptor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    design_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pricing
    estimated_new_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_new_price_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resale_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    resale_price_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resale_price_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resale_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Analysis bookkeeping
    analysis_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # pending/ok/error/skipped
    analysis_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    case: Mapped["Case | None"] = relationship(  # noqa: F821
        back_populates="hats", lazy="selectin"
    )
    colors: Mapped[list["HatColor"]] = relationship(  # noqa: F821
        back_populates="hat", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def display_id(self) -> str | None:
        if self.case and self.position_in_case is not None:
            return f"{self.case.display_id}-{self.position_in_case:02d}"
        return None
