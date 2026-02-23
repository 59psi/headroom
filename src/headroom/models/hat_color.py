from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from headroom.database import Base


class HatColor(Base):
    __tablename__ = "hat_colors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hat_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hats.id", ondelete="CASCADE")
    )
    color_name: Mapped[str] = mapped_column(String(50), index=True)
    general_color: Mapped[str] = mapped_column(String(30), index=True, default="")
    hex_value: Mapped[str] = mapped_column(String(7))
    dominance_rank: Mapped[int] = mapped_column(Integer)

    hat: Mapped["Hat"] = relationship(back_populates="colors")  # noqa: F821
