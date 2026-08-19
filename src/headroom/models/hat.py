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
    # The processed JPEG the cutout was made from, kept so the background can be
    # redone later. Before this the JPEG was deleted the moment rembg succeeded,
    # which meant a bad cutout could only be fixed by re-uploading the photo.
    original_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Small WebP derivative for the gallery grid — see utils/photo.
    thumb_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
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

    # The long-form write-up. Distinct from `design_notes`, which is one
    # sentence about what the hat looks like: this is several paragraphs about
    # what it IS — the collection or collab it belongs to, what that drop was,
    # and where this colourway sits in it. Written by Claude and rewritten
    # whenever the hat is re-analysed or its collection changes, so it is
    # derived data and never the place to keep something you typed. That is
    # what `owner_notes` is for, which nothing but you ever writes.
    story: Mapped[str | None] = mapped_column(Text, nullable=True)
    story_generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Queued for (re)writing. A column rather than in-memory state so a restart
    # mid-queue doesn't strand a hat without its write-up — same reason
    # `analysis_status='pending'` is persisted.
    story_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Yours. Never written by any analysis path, never cleared by a refresh.
    owner_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    # How much `resale_price` is actually about THIS hat. The three values are
    # not degrees of confidence in one measurement -- they are three different
    # measurements that happen to share a column:
    #   "manual"   -- a person typed it. Authoritative; nothing is applied to it.
    #   "model"    -- median asking price of listings matching this model name.
    #                 A comparable. Still an ASK, so valuation discounts it.
    #   "category" -- median asking price of every listing in the style category,
    #                 because too few model listings existed to be worth using.
    #                 That is a price level for "an Odysea", not a value for this
    #                 Odysea, and treating it as one gave every hat in a category
    #                 the same number and made the collection total meaningless.
    # `resale_price_source` carries the same fact inside a display sentence;
    # valuation needs to branch on it, and parsing prose for " model listings"
    # would silently start valuing the collection differently the day someone
    # reworded the label.
    resale_price_scope: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Analysis bookkeeping
    # What logo/wordmark the analyser actually SAW, and whose it is — kept apart
    # from `brand` because that can be inferred from shape, colourway or a hang
    # tag with no logo in frame at all. This one answers "was a mark visible,
    # and who owns it", which is the difference between a guess and evidence.
    # What the hat is BUILT from, free-form. Construction is orthogonal to the
    # model line -- melin offers a given build across A-Game, Coronado, Trenches
    # and the rest, so ANY hat can be any of them, which is why this is its own
    # field and not a HatStyle value.
    #
    # Free-form and not an enum because melin ships specialty fabrics whenever
    # they feel like it (seasonal drops, collab-only materials). An enum makes
    # every one of those unrecordable until someone ships a migration, so the
    # owner holding the hat and reading its tag loses to a list written months
    # earlier. `hydro` / `hydrolite` below stay as the indexed fast path for the
    # two common values; `set_construction()` is the only writer of all three.
    construction: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # DERIVED from `construction` -- do not assign directly, call
    # `set_construction()`. Kept as real columns rather than properties because
    # search filters and the pricing prompt query them, and a @property cannot
    # appear in a WHERE clause.
    hydrolite: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
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
    # Which step of the pipeline is running right now, while analysis_status is
    # 'pending'. Deliberately NOT cleared when the run finishes: eight separate
    # places set a terminal status, and one of them forgetting to also null this
    # would leave a stale stage on screen forever. `HatRead` masks it to null on
    # any non-pending status instead, so the invariant holds in one place. The
    # column keeping its last value is the intended cost of that.
    analysis_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Which bulk re-analysis run this hat belongs to, if any. Indexed because
    # progress for a job is a COUNT over exactly this column.
    analysis_job_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
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

    def set_construction(self, value: str | None) -> None:
        """Record the construction and re-derive the two indexed flags.

        The ONLY writer of `construction`, `hydro` and `hydrolite`. Assigning
        the flags by hand is what lets them drift out of step with the text a
        person actually typed, so they are derived here every time instead.

        Substring matching, not equality: real answers arrive as "A-Game Hydro",
        "Hydro Thermal" or "HYDROLite" depending on whether the speaker is
        reading a tag, a product page or a hang label. HYDROLite is checked
        first because it contains "hydro" — order is load-bearing.
        """
        cleaned = (value or "").strip()
        self.construction = cleaned or None
        key = cleaned.lower().replace("-", "").replace(" ", "")
        self.hydrolite = "hydrolite" in key
        self.hydro = "hydro" in key and not self.hydrolite

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
