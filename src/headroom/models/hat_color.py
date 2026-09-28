from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from headroom.database import Base


class HatColor(Base):
    __tablename__ = "hat_colors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # No `ondelete="CASCADE"`. It was declared here and never happened: SQLite
    # enforces no foreign key without `PRAGMA foreign_keys=ON`, which this app
    # does not set, so the clause promised a database-level cascade the engine
    # never performed (a row for a hat that does not exist inserts cleanly).
    # The cascade that actually runs is the ORM's — `Hat.colors` is
    # `cascade="all, delete-orphan"` — and the schema now claims no more.
    hat_id: Mapped[int] = mapped_column(Integer, ForeignKey("hats.id"))
    color_name: Mapped[str] = mapped_column(String(50), index=True)
    # `server_default` matches `database._HAT_COLOR_COLUMN_DDL`, so a fresh
    # install and an upgraded one build the same column (the parity test in
    # `tests/test_schema_consistency.py` compares defaults and NOT NULL).
    general_color: Mapped[str] = mapped_column(
        String(30), index=True, default="", server_default=""
    )
    hex_value: Mapped[str] = mapped_column(String(7))
    dominance_rank: Mapped[int] = mapped_column(Integer)
    # primary | secondary | tertiary | accent
    tier: Mapped[str] = mapped_column(
        String(12), default="primary", server_default="primary"
    )

    # `lazy="raise"`: nothing reads a color's hat — colors are only ever
    # reached FROM their hat — and the default ("select") is not a quieter
    # option under AsyncSession, it is a `MissingGreenlet` at the access.
    # "raise" fails at the same place with a message that names the
    # relationship. The backref still keeps `hat.colors.append(...)` and the
    # delete-orphan cascade working; neither loads this side.
    hat: Mapped["Hat"] = relationship(back_populates="colors", lazy="raise")  # noqa: F821
