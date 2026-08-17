from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func, text
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
    is_beanie: Mapped[bool] = mapped_column(Boolean, default=False)

    # AI-detected attributes
    brand: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Official colorway name ("Heather Ocean") — user-picked from the catalog
    # or set by the purchase-history importer; Claude doesn't know these.
    colorway: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model_confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)  # high/medium/low
    style_descriptor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    design_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pricing
    # Cost basis — what was actually paid (purchase-history import or manual)
    purchase_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    estimated_new_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_new_price_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resale_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    resale_price_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resale_price_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resale_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Analysis bookkeeping
    # What logo/wordmark the analyser actually SAW, and whose it is — kept apart
    # from `brand` because that can be inferred from shape, colourway or a hang
    # tag with no logo in frame at all. This one answers "was a mark visible,
    # and who owns it", which is the difference between a guess and evidence.
    # HYDROLite is melin CONSTRUCTION, not a model line: featherweight build,
    # bonded seams, gel-welded logos, antimicrobial sweatband. It is offered
    # across A-Game, Coronado, Trenches and the rest, so ANY hat can be one --
    # which is exactly why it is a flag here and not a HatStyle value. Making it
    # a style would have forced a second entry per model and split one model's
    # hats across two style buckets.
    hydrolite: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    # HYDRO is the sibling technology — melin lists HYDRO and HYDROLite as
    # separate collections, so they get separate flags. A hat is realistically
    # one or the other, but that is not enforced in the schema: the analyser
    # picks at most one (see the `construction` tool field) and a human is
    # allowed to record whatever the hat in their hand actually says.
    hydro: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    # Named artist / signature collaboration, when the hat is one. melin brands
    # these as Signature Collaborations and Special Projects and names them for
    # the collaborator ("Skye Walker", "melin x OluKai"), so this holds that
    # name. Distinct from the `collab` STYLE, which only says "some collab" —
    # this says WHICH, which is the part that drives collectability and resale.
    artist_series: Mapped[str | None] = mapped_column(String(160), nullable=True)

    logo_detected: Mapped[str | None] = mapped_column(String(255), nullable=True)

    analysis_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # pending/ok/fallback/skipped/error
    analysis_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # v0.3 — disposition (sold/gifted/lost/trashed/trade)
    disposed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    disposed_via: Mapped[str | None] = mapped_column(String(20), nullable=True)
    disposed_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    disposed_to: Mapped[str | None] = mapped_column(String(120), nullable=True)
    disposed_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # v0.4 — eBay live comparable-listings prices
    ebay_avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ebay_median_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ebay_listing_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ebay_search_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ebay_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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
    wear_logs: Mapped[list["WearLog"]] = relationship(  # noqa: F821
        lazy="selectin", cascade="all, delete-orphan", order_by="WearLog.worn_at"
    )

    # Derived read-model values. They live here rather than in the route layer
    # so `HatRead.model_validate(hat)` can populate itself straight off the ORM
    # object, and so nothing outside has to walk `hat.case.room` by hand.

    @property
    def display_id(self) -> str | None:
        if self.case and self.position_in_case is not None:
            return f"{self.case.display_id}-{self.position_in_case:02d}"
        return None

    @property
    def case_display_id(self) -> str | None:
        return self.case.display_id if self.case else None

    @property
    def case_type(self) -> str | None:
        return self.case.case_type if self.case else None

    @property
    def room(self) -> "Room | None":  # noqa: F821
        """The room this hat sits in, via its case. None when unassigned."""
        return self.case.room if self.case else None

    @property
    def room_id(self) -> int | None:
        room = self.room
        return room.id if room else None

    @property
    def room_name(self) -> str | None:
        room = self.room
        return room.name if room else None

    @property
    def wear_count(self) -> int:
        return len(self.wear_logs or [])
