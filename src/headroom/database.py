import logging
import os
from collections.abc import AsyncGenerator

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from headroom.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


#: The only values allowed to reach `PRAGMA synchronous=`.
#:
#: A whitelist rather than a validated string, because a PRAGMA cannot take a
#: bound parameter — the value is interpolated into SQL, so it must come from a
#: closed set rather than from anything a person can type.
SYNCHRONOUS_MODES = ("FULL", "EXTRA", "NORMAL", "OFF")

DEFAULT_SYNCHRONOUS = "FULL"


def sqlite_synchronous() -> str:
    """The `synchronous` mode to apply, defaulting to the durable one.

    Anything unrecognized falls back to the default instead of being passed
    through: a typo in an env var must not silently turn durability off.
    """
    raw = os.environ.get("HEADROOM_SQLITE_SYNCHRONOUS", "").strip().upper()
    if raw in SYNCHRONOUS_MODES:
        return raw
    if raw:
        logger.warning(
            "Ignoring HEADROOM_SQLITE_SYNCHRONOUS=%r — not one of %s; using %s",
            raw, ", ".join(SYNCHRONOUS_MODES), DEFAULT_SYNCHRONOUS,
        )
    return DEFAULT_SYNCHRONOUS


async def checkpoint_wal() -> None:
    """Fold the WAL back into the main database file.

    Called on graceful shutdown. `synchronous=FULL` already makes each commit
    durable, so this is not about losing transactions — it is about what a
    later power cut finds on disk. A truncated WAL means the next boot has
    nothing to replay, which is one fewer moving part in exactly the situation
    that started all of this.

    Best-effort: a failure here must not turn a clean shutdown into a crash.
    """
    if engine.dialect.name != "sqlite":
        return
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        logger.info("WAL checkpointed on shutdown")
    except Exception as exc:  # noqa: BLE001 — never break shutdown
        logger.warning("WAL checkpoint on shutdown failed: %s", exc)


if engine.dialect.name == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - connect hook
        """Tune SQLite for a multi-writer single-process app on a Pi.

        WAL lets readers proceed during a write; busy_timeout makes writers
        wait out a lock instead of raising 'database is locked' immediately —
        directly shrinking the transient-lock error class that could otherwise
        surface on the import worker and background loops.

        **`synchronous=FULL`, and that is a deliberate reversal.** This was
        `NORMAL` — SQLite's own recommendation for WAL, and the setting most
        guides suggest. Under `NORMAL` the WAL is *not* fsynced when a
        transaction commits; it is synced at a checkpoint. SQLite's
        documentation is explicit that this is safe from corruption but not
        from loss: a transaction committed under `NORMAL` "might roll back
        following a power loss". The default checkpoint threshold is 1000
        pages, so what is at risk is not the last write — it is every write
        since the last checkpoint.

        This deployment established that the risk is not theoretical. An
        unclean shutdown destroyed Caddy's stored private key and a lock file
        on the same SD card — written, never synced, gone — which broke HTTPS
        for 37 days. The database sits on that card, under the same power, with
        durability switched off. "The database is never corrupted" is small
        comfort when the missing rows are the hats you photographed that
        afternoon.

        `FULL` costs one fsync per commit. That is the right trade here and it
        is not close: this is a personal inventory doing a handful of writes
        per interaction, not a write-heavy service. The worst case is bulk
        import at one commit per photo — a hundred extra fsyncs, once.

        `HEADROOM_SQLITE_SYNCHRONOUS` overrides it for anyone whose hardware
        makes that trade differently, but the default is durable.
        """
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            # Whitelisted, not interpolated: this reaches a PRAGMA, which
            # cannot take a bound parameter.
            cur.execute(f"PRAGMA synchronous={sqlite_synchronous()}")
        finally:
            cur.close()


class Base(DeclarativeBase):
    pass


# Static, fully-formed DDL — column names and types are hard-coded literals,
# so no interpolation is needed and SQL injection is structurally impossible.
# Same contract as `_HAT_COLUMN_DDL` below: fully-static DDL, one entry per
# column added after the table first shipped. `purchases` is created by
# `Base.metadata.create_all`, which only ever CREATEs — it will not alter a
# table that already exists, so a column added to the model without an entry
# here is present on new installs and missing on every upgraded one.
_PURCHASE_COLUMN_DDL: dict[str, str] = {
    # v2.19 — the size on the order line, so matching can tell two sizes of the
    # same model apart instead of binding to whichever hat comes back first.
    "size": "ALTER TABLE purchases ADD COLUMN size VARCHAR(20)",
}

_HAT_COLUMN_DDL: dict[str, str] = {
    "original_path": "ALTER TABLE hats ADD COLUMN original_path VARCHAR(255)",
    "thumb_path": "ALTER TABLE hats ADD COLUMN thumb_path VARCHAR(255)",
    "brand": "ALTER TABLE hats ADD COLUMN brand VARCHAR(80)",
    "logo_detected": "ALTER TABLE hats ADD COLUMN logo_detected VARCHAR(255)",
    "hydrolite": "ALTER TABLE hats ADD COLUMN hydrolite BOOLEAN NOT NULL DEFAULT 0",
    "hydro": "ALTER TABLE hats ADD COLUMN hydro BOOLEAN NOT NULL DEFAULT 0",
    # v2.11 — free-form construction. `hydro`/`hydrolite` became derived from
    # this; `_backfill_construction()` seeds it from them for existing rows.
    "construction": "ALTER TABLE hats ADD COLUMN construction VARCHAR(80)",
    "artist_series": "ALTER TABLE hats ADD COLUMN artist_series VARCHAR(160)",
    "model_name": "ALTER TABLE hats ADD COLUMN model_name VARCHAR(120)",
    "model_confidence": "ALTER TABLE hats ADD COLUMN model_confidence VARCHAR(10)",
    "style_descriptor": "ALTER TABLE hats ADD COLUMN style_descriptor VARCHAR(120)",
    "design_notes": "ALTER TABLE hats ADD COLUMN design_notes TEXT",
    # v2.24 — the notes only you write.
    "owner_notes": "ALTER TABLE hats ADD COLUMN owner_notes TEXT",
    "estimated_new_price": "ALTER TABLE hats ADD COLUMN estimated_new_price FLOAT",
    "estimated_new_price_source": "ALTER TABLE hats ADD COLUMN estimated_new_price_source VARCHAR(80)",
    "resale_price": "ALTER TABLE hats ADD COLUMN resale_price FLOAT",
    "resale_price_source": "ALTER TABLE hats ADD COLUMN resale_price_source VARCHAR(80)",
    "resale_price_url": "ALTER TABLE hats ADD COLUMN resale_price_url VARCHAR(500)",
    "resale_checked_at": "ALTER TABLE hats ADD COLUMN resale_checked_at DATETIME",
    # v2.19 — "manual" | "model" | "category": what resale_price is a price OF.
    "resale_price_scope": "ALTER TABLE hats ADD COLUMN resale_price_scope VARCHAR(20)",
    # v2.33 — a hat kept in a room with no case (a shelf, a hook, a stand).
    # No FK clause: SQLite cannot add a column with a REFERENCES constraint to
    # an existing table, and the app enforces the relationship anyway.
    "direct_room_id": "ALTER TABLE hats ADD COLUMN direct_room_id INTEGER",
    # v2.33 — special/limited runs, stated by the owner.
    "limited_edition": "ALTER TABLE hats ADD COLUMN limited_edition BOOLEAN NOT NULL DEFAULT 0",
    "analysis_status": "ALTER TABLE hats ADD COLUMN analysis_status VARCHAR(20)",
    "analysis_stage": "ALTER TABLE hats ADD COLUMN analysis_stage VARCHAR(20)",
    "analysis_stage_at": "ALTER TABLE hats ADD COLUMN analysis_stage_at DATETIME",
    "analysis_job_id": "ALTER TABLE hats ADD COLUMN analysis_job_id INTEGER",
    "analysis_error": "ALTER TABLE hats ADD COLUMN analysis_error TEXT",
    "analyzed_at": "ALTER TABLE hats ADD COLUMN analyzed_at DATETIME",
    # v0.3 — disposition (sold/gifted/lost/trashed/trade)
    "disposed_at": "ALTER TABLE hats ADD COLUMN disposed_at DATETIME",
    "disposed_via": "ALTER TABLE hats ADD COLUMN disposed_via VARCHAR(20)",
    "disposed_price": "ALTER TABLE hats ADD COLUMN disposed_price FLOAT",
    "disposed_to": "ALTER TABLE hats ADD COLUMN disposed_to VARCHAR(120)",
    "disposed_notes": "ALTER TABLE hats ADD COLUMN disposed_notes TEXT",
    # v1.1 — colorway catalog + purchase-history cost basis
    "colorway": "ALTER TABLE hats ADD COLUMN colorway VARCHAR(120)",
    "purchase_price": "ALTER TABLE hats ADD COLUMN purchase_price FLOAT",
    "purchased_at": "ALTER TABLE hats ADD COLUMN purchased_at DATETIME",
    # v0.4 — eBay live comparable-listings prices
    "ebay_avg_price": "ALTER TABLE hats ADD COLUMN ebay_avg_price FLOAT",
    "ebay_median_price": "ALTER TABLE hats ADD COLUMN ebay_median_price FLOAT",
    "ebay_listing_count": "ALTER TABLE hats ADD COLUMN ebay_listing_count INTEGER",
    "ebay_search_url": "ALTER TABLE hats ADD COLUMN ebay_search_url VARCHAR(500)",
    "ebay_checked_at": "ALTER TABLE hats ADD COLUMN ebay_checked_at DATETIME",
}


def _run_migrations(conn) -> None:
    """Add missing tables and columns to existing databases."""
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    if "rooms" not in existing_tables:
        conn.execute(
            text(
                "CREATE TABLE rooms ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  name VARCHAR(100) UNIQUE NOT NULL,"
                "  is_default BOOLEAN NOT NULL DEFAULT 0,"
                "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
                "  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )

    if "app_settings" not in existing_tables:
        conn.execute(
            text(
                "CREATE TABLE app_settings ("
                "  key VARCHAR(64) PRIMARY KEY,"
                "  value TEXT,"
                "  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )

    # Re-inspect rather than reuse `existing_tables`: that snapshot predates the
    # CREATE TABLE above, so on a *fresh* database it would say "no rooms table"
    # and skip the column check entirely — while `create_all` is then a no-op
    # because the table now exists. That combination shipped a fresh container
    # with a rooms table missing is_default and crashed on boot.
    if "rooms" in inspect(conn).get_table_names():
        columns = [c["name"] for c in inspect(conn).get_columns("rooms")]
        # v2.4 — the fallback room became a flag instead of a hardcoded id=1.
        # Backfill picks the lowest id rather than literally 1, so a database
        # whose original room was renamed or re-keyed still ends up with exactly
        # one default. `ensure_default_room()` re-checks the invariant on boot.
        if "is_default" not in columns:
            conn.execute(
                text("ALTER TABLE rooms ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT 0")
            )
            conn.execute(
                text("UPDATE rooms SET is_default = 1 WHERE id = (SELECT MIN(id) FROM rooms)")
            )

    if "cases" in existing_tables:
        columns = [c["name"] for c in inspector.get_columns("cases")]
        if "room_id" not in columns:
            conn.execute(
                text("ALTER TABLE cases ADD COLUMN room_id INTEGER DEFAULT 1 REFERENCES rooms(id)")
            )
        # v0.9 — per-case capacity override (NULL → type default)
        if "capacity" not in columns:
            conn.execute(text("ALTER TABLE cases ADD COLUMN capacity INTEGER"))

    if "hat_colors" in existing_tables:
        columns = [c["name"] for c in inspector.get_columns("hat_colors")]
        if "general_color" not in columns:
            conn.execute(
                text("ALTER TABLE hat_colors ADD COLUMN general_color VARCHAR(30) DEFAULT ''")
            )
        if "tier" not in columns:
            conn.execute(
                text("ALTER TABLE hat_colors ADD COLUMN tier VARCHAR(12) DEFAULT 'primary'")
            )

    if "wear_log" in existing_tables:
        # Enforce one wear per hat per day on already-created tables: dedupe any
        # pre-constraint rows (keep the earliest), then add the unique index.
        conn.execute(
            text(
                "DELETE FROM wear_log WHERE id NOT IN "
                "(SELECT MIN(id) FROM wear_log GROUP BY hat_id, worn_at)"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_wear_hat_day "
                "ON wear_log(hat_id, worn_at)"
            )
        )

    if "hats" in existing_tables:
        conn.execute(
            text("UPDATE hats SET size = 'classic' WHERE size = 'standard'")
        )
        existing_cols = {c["name"] for c in inspector.get_columns("hats")}
        for col_name, ddl in _HAT_COLUMN_DDL.items():
            if col_name not in existing_cols:
                conn.execute(text(ddl))
        _backfill_construction(conn)

    if "purchases" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("purchases")}
        for col_name, ddl in _PURCHASE_COLUMN_DDL.items():
            if col_name not in existing_cols:
                conn.execute(text(ddl))


def _backfill_construction(conn) -> None:
    """Seed free-form `construction` from the flags that used to be the truth.

    Only fills rows where it is NULL, so it is idempotent and never overwrites
    a value someone typed. HYDROLite first: a row with both flags set (the old
    schema permitted it) is the more specific of the two.
    """
    conn.execute(
        text(
            "UPDATE hats SET construction = 'HYDROLite' "
            "WHERE construction IS NULL AND hydrolite = 1"
        )
    )
    conn.execute(
        text(
            "UPDATE hats SET construction = 'HYDRO' "
            "WHERE construction IS NULL AND hydro = 1"
        )
    )


async def ensure_default_room() -> None:
    """Guarantee exactly one room carries `is_default`. Raw SQL to avoid
    cascading relationship loads.

    Repairs three states on every boot:
      * no rooms at all        -> create 'Default Room' and flag it
      * rooms but none flagged -> flag the lowest id
      * more than one flagged  -> keep the lowest id, clear the rest

    The flag is what makes a room the reassignment target and the default for
    new cases, so "exactly one" is a real invariant, not a nicety — zero flagged
    rooms would break case creation, and two would make the target ambiguous.
    """
    async with async_session() as db:
        if not (await db.execute(text("SELECT COUNT(*) FROM rooms"))).scalar():
            await db.execute(
                text("INSERT INTO rooms (name, is_default) VALUES ('Default Room', 1)")
            )
            await db.commit()
            return

        flagged = (
            await db.execute(text("SELECT COUNT(*) FROM rooms WHERE is_default = 1"))
        ).scalar()
        if flagged == 1:
            return
        await db.execute(text("UPDATE rooms SET is_default = 0"))
        await db.execute(
            text("UPDATE rooms SET is_default = 1 WHERE id = (SELECT MIN(id) FROM rooms)")
        )
        await db.commit()


async def reattach_orphaned_cases() -> None:
    """Move cases whose room no longer exists onto the default room.

    Companion to `ensure_default_room` — same idea, one level down: that one
    guarantees a default room exists, this one guarantees every case actually
    points at a room. It therefore CALLS that one rather than relying on the
    caller to order them: the `is_default = 1` subquery below returns NULL if
    no room is flagged, which would set every orphan's `room_id` to NULL — the
    exact state this repairs, made permanent. The dependency is real, so it is
    expressed in code instead of as a comment about call order. Both are
    idempotent, so invoking it twice on the boot path costs one cheap query.

    Orphans were reachable because there is no `PRAGMA foreign_keys` and
    `create_case` never validated `room_id`, while the frontend sent a
    hardcoded `1` regardless of what the picker showed (fixed in 2.7.0). Delete
    the room that happened to be id 1 — which the `is_default` flag exists to
    let you do — and every case created afterwards pointed at nothing. The
    symptoms don't name the cause: the room reads "Unknown" on the case, and
    the room it *should* belong to reports zero cases.

    Raw SQL, matching `ensure_default_room`, to avoid cascading relationship
    loads on the boot path.
    """
    async with async_session() as db:
        orphans = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM cases WHERE room_id IS NULL OR room_id NOT IN"
                    " (SELECT id FROM rooms)"
                )
            )
        ).scalar()
        if not orphans:
            return
    # Only now that there is work to do, and outside the session above so the
    # repair runs in its own. Guarantees the subquery below resolves.
    await ensure_default_room()
    async with async_session() as db:
        await db.execute(
            text(
                "UPDATE cases SET room_id = (SELECT id FROM rooms WHERE is_default = 1)"
                " WHERE room_id IS NULL OR room_id NOT IN (SELECT id FROM rooms)"
            )
        )
        await db.commit()
        logger.warning(
            "Reattached %d case(s) whose room no longer existed to the default room.",
            orphans,
        )


async def init_db() -> None:
    from headroom.models import __all_models__  # noqa: F811

    _ = __all_models__  # ensure models are registered

    async with engine.begin() as conn:
        await conn.run_sync(_run_migrations)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await ensure_default_room()
    await reattach_orphaned_cases()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
