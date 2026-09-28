from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from headroom.database import Base, UtcDateTime
from headroom.models.wear_log import WearLog


class ResaleScope(StrEnum):
    """What `Hat.resale_price` is a price OF — the one definition.

    Three different measurements that share a column, not degrees of confidence
    in one. Seven modules compared against the bare strings and one of them had
    its own `MANUAL_SCOPE`; this is the enum they all read now.

    `resale_price_source` carries the same fact inside a display sentence;
    valuation branches on THIS, because parsing prose for " model listings"
    would silently start valuing the collection differently the day someone
    reworded the label.
    """

    #: A person typed it. Authoritative; nothing is ever applied to it.
    MANUAL = "manual"
    #: Median asking price of listings matching this model name (or, with a
    #: colorway, this exact product). A comparable, used AS-IS: melinrecap is a
    #: fixed-price marketplace, so the ask is the sale price and valuation does
    #: not discount it.
    MODEL = "model"
    #: Median asking price of every listing in the style category, because too
    #: few model listings existed to be worth using. A price level for "an
    #: Odysea", not a value for THIS Odysea — treating it as one gave every hat
    #: in a category the same number and made the collection total meaningless.
    CATEGORY = "category"


# ---- the price-provenance clumps ------------------------------------------- #
#
# Each group below is a set of columns that are only ever meaningful together:
# a price without its source, or a comparable without the date it was checked,
# is a number nobody can act on. They lived as loose parallel columns in the
# body of `Hat`, each restated field-by-field wherever it travelled. Declaring
# each group once, as a mixin, makes the clump a named thing — the unit
# `schemas.hat.HatRead` and `schemas.admin.EbayComps` mirror — rather than a
# convention of adjacency. The columns themselves are unchanged (same names,
# same types, still flat on `hats`), so no migration is involved.


class NewPriceColumns:
    """What the hat costs new, and who said so."""

    estimated_new_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_new_price_source: Mapped[str | None] = mapped_column(String(80), nullable=True)


class ResaleColumns:
    """The resale observation: a price, where it came from, when, and of what.

    `resale_price_scope` is a `ResaleScope` — see that enum for what each
    value means; it is the one definition and is not restated here.
    """

    resale_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    resale_price_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resale_price_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resale_checked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    resale_price_scope: Mapped[str | None] = mapped_column(String(20), nullable=True)


class EbayCompsColumns:
    """v0.4 — eBay live comparable-listings prices, as of `ebay_checked_at`."""

    ebay_avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ebay_median_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ebay_listing_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ebay_search_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ebay_checked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class DispositionColumns:
    """v0.3 — how the hat left the collection (sold/gifted/lost/trashed/trade).

    `disposed_at` is the flag: a disposed hat stays in the database, frees its
    case slot, and keeps the other four as the record of where it went.
    """

    disposed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    disposed_via: Mapped[str | None] = mapped_column(String(20), nullable=True)
    disposed_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    disposed_to: Mapped[str | None] = mapped_column(String(120), nullable=True)
    disposed_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Hat(NewPriceColumns, ResaleColumns, EbayCompsColumns, DispositionColumns, Base):
    __tablename__ = "hats"
    __table_args__ = (
        # Two ACTIVE hats can never share a slot. `display_id` is derived from
        # case + position, so a duplicate here is two hats with one label —
        # which is what a concurrency gap produced before the placement lock
        # existed. Partial: a disposed hat keeps its old position as history
        # and `undispose` re-slots it, so only live rows are constrained.
        # Existing databases get the same index from `database._run_migrations`
        # after `_repair_duplicate_positions` has renumbered any fallout.
        Index(
            "ux_hats_case_position",
            "case_id",
            "position_in_case",
            unique=True,
            sqlite_where=text("case_id IS NOT NULL AND disposed_at IS NULL"),
        ),
        # AUTOINCREMENT: a hat's id is never reused. Without it SQLite hands out
        # max(id)+1, so deleting the newest hat gave its id to the next one
        # created — and a hat's NFC/QR tag is `/t/h/<id>`, printed on a sticker
        # that cannot be rewritten. The old sticker kept scanning and silently
        # opened the new hat, one tap from logging a wear against it. Existing
        # databases are rebuilt once by `database._rebuild_hats_autoincrement`,
        # which also carries the high-water mark of ids already handed out.
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cases.id"), nullable=True
    )
    position_in_case: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # A hat kept in a room with NO case — on a shelf, a hook, a stand.
    #
    # Rooms contain Cases contain Hats was the whole model, so a hat outside a
    # case was nowhere: `room` walked `self.case.room`, and a caseless hat
    # reported no room at all. That is not how the collection actually sits.
    # Caddies and Aviators do not fit a three-hat travel case, special editions
    # get displayed rather than packed, and plenty of hats are simply out.
    #
    # Meaningful only when `case_id` is NULL: a hat in a case takes that case's
    # room, and `hat_service` clears one whenever it sets the other so the two
    # can never both be set and disagree.
    direct_room_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("rooms.id"), nullable=True
    )
    # Special/limited runs. Not derived from anything — a hat is limited
    # because the drop was, which no photo and no field can tell you.
    # `server_default` matches `_HAT_COLUMN_DDL` ("NOT NULL DEFAULT 0"), so a
    # fresh install and an upgraded one build the same column; without it a
    # raw INSERT that omits the flag worked on one and failed on the other.
    limited_edition: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
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

    # Yours. Never written by any analysis path, never cleared by a refresh —
    # the only free-text field on a hat that a re-analysis cannot touch.
    owner_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pricing. Cost basis — what was actually paid (purchase-history import or
    # manual). The new-price, resale and eBay clumps are the mixins above.
    purchase_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    purchased_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # Analysis bookkeeping
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
    # Who wrote the construction now standing: `construction_audit.OWNER_SOURCE`
    # when a person typed or chose it, NULL when analysis (or an import) did.
    # The construction audit's bulk clear/reassign skips owner values by this
    # column, so an owner's correction survives the sweep meant for the
    # analyzer's guesses — and survives the activity log's retention prune,
    # which a check against the audit log alone would not. Written only by
    # `set_construction()`, like the flags below.
    construction_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
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

    # What logo/wordmark the analyzer actually SAW, and whose it is — kept apart
    # from `brand` because that can be inferred from shape, colorway or a hang
    # tag with no logo in frame at all. This one answers "was a mark visible,
    # and who owns it", which is the difference between a guess and evidence.
    logo_detected: Mapped[str | None] = mapped_column(String(255), nullable=True)

    analysis_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # pending/ok/fallback/skipped/error
    # Which step of the pipeline is running right now, while analysis_status is
    # 'pending'. Deliberately NOT cleared when the run finishes: eight separate
    # places set a terminal status, and one of them forgetting to also null this
    # would leave a stale stage on screen forever. `HatRead` masks it to null on
    # any non-pending status instead, so the invariant holds in one place. The
    # column keeping its last value is the intended cost of that.
    analysis_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: When `analysis_stage` last changed. A stage on its own cannot tell a
    #: pipeline that is working from one that is wedged — both read
    #: "identifying" — so the UI can only say "Analyzing…" and hope. With a
    #: timestamp it can say "in identifying for 41 min", which is the same
    #: information a person would use to decide something is stuck.
    analysis_stage_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Which bulk re-analysis run this hat belongs to, if any. Indexed because
    # progress for a job is a COUNT over exactly this column. The column
    # arrived by ALTER in 2.10, so upgraded databases get the index from
    # `database._INDEX_DDL`, not from this declaration.
    analysis_job_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    analysis_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Who set the colors: 'owner' (`hat_service.COLORS_OWNER_SOURCE`) when a
    # person set them via PUT /api/hats/{id}/colors; NULL means analysis wrote
    # them. Re-analysis replaces only the second kind, so a corrected palette
    # survives Reanalyze. Same shape as `construction_source`.
    colors_source: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, server_default=func.now(), onupdate=func.now()
    )

    #: How many days this hat has been worn — counted by the database in the
    #: same SELECT that loads the hat.
    #:
    #: This was `len(self.wear_logs)`, which is why `wear_logs` was a selectin
    #: collection: every hat list loaded every wear row of every hat in it to
    #: produce one integer per hat. The count is the only thing any listing
    #: needs; the rows are wanted only by the two handlers that edit them.
    wear_count: Mapped[int] = column_property(
        select(func.count(WearLog.id))
        .where(WearLog.hat_id == id)
        .correlate_except(WearLog)
        .scalar_subquery()
    )

    # Many-to-one and selectin: one row, needed by every read model (the
    # `display_id` / `room` properties below). `direct_room` used to drag its
    # room's whole shelf in through `Room.cases`; neither cascades further now
    # that `Case.hats` and `Room.cases` are "raise".
    case: Mapped["Case | None"] = relationship(  # noqa: F821
        back_populates="hats", lazy="selectin"
    )
    # No `back_populates`: Room does not need a hats collection, and adding one
    # would give a room two sources of hats (its cases' hats, and these) that
    # every caller would then have to remember to union.
    direct_room: Mapped["Room | None"] = relationship(  # noqa: F821
        foreign_keys=[direct_room_id], lazy="selectin"
    )
    # A handful per hat, and `HatRead` renders every one of them.
    colors: Mapped[list["HatColor"]] = relationship(  # noqa: F821
        back_populates="hat", lazy="selectin", cascade="all, delete-orphan"
    )
    # `lazy="raise"`: see `wear_count`. Load with `selectinload(Hat.wear_logs)`
    # where the rows themselves are wanted. The delete-orphan cascade still
    # runs — a flush loads the collection itself when it deletes a hat.
    wear_logs: Mapped[list["WearLog"]] = relationship(
        lazy="raise", cascade="all, delete-orphan", order_by="WearLog.worn_at"
    )

    def detach_from_case(self, room_id: int | None) -> None:
        """Take this hat out of its case, leaving it loose in `room_id`.

        The ONLY writer of "no longer in a case". Since 2.33 a hat can live in
        a room with no case, so clearing `case_id` alone stopped meaning "still
        on that shelf" and started meaning "nowhere" — reachable only from the
        Hats list and search. Two callers detach a hat and each had its own
        answer: `case_service.delete_case` learned to carry the room across in
        2.57.0, and `hat_service.undispose_hat`'s can't-fit fallback did not,
        so restoring a hat into a full case silently un-roomed it. That is a
        mechanism with three implementations, which is why it lives here beside
        `set_construction` rather than at either call site.

        `room_id=None` is still available and still means "nowhere" — but it
        has to be asked for now, rather than being what you get by forgetting.
        """
        self.case_id = None
        self.position_in_case = None
        self.direct_room_id = room_id

    def set_construction(self, value: str | None, *, source: str | None = None) -> None:
        """Record the construction and re-derive the two indexed flags.

        The ONLY writer of `construction`, `construction_source`, `hydro` and
        `hydrolite`. Assigning the flags by hand is what lets them drift out of
        step with the text a person actually typed, so they are derived here
        every time instead.

        `source` records who wrote a NEW value — `construction_audit.
        OWNER_SOURCE` for a person, None for analysis or an import. Re-writing
        the value already there, in any spelling, keeps its provenance: a
        vocabulary snap ("hydro" → "Hydro") or an Edit form re-sending a field
        the owner never touched is not a new assertion, and must neither
        promote the analyzer's guess to the owner's nor demote the owner's
        answer to a guess. Clearing clears both.

        Substring matching, not equality: real answers arrive as "A-Game Hydro",
        "Hydro Thermal" or "HYDROLite" depending on whether the speaker is
        reading a tag, a product page or a hang label. HYDROLite is checked
        first because it contains "hydro" — order is load-bearing.
        """
        cleaned = (value or "").strip()
        rewrite = bool(cleaned) and cleaned.casefold() == (self.construction or "").casefold()
        self.construction = cleaned or None
        if not rewrite:
            self.construction_source = source if self.construction else None
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
        """The room this hat sits in — via its case, or directly.

        A cased hat takes its case's room; the case is the thing that moved.
        A caseless hat can still be somewhere: on a shelf, a hook, a stand.
        Only one of the two can be set (`hat_service` clears the other), so
        the order here is a tiebreak that should never be needed.
        """
        if self.case:
            return self.case.room
        return self.direct_room

    @property
    def room_id(self) -> int | None:
        room = self.room
        return room.id if room else None

    @property
    def room_name(self) -> str | None:
        room = self.room
        return room.name if room else None
