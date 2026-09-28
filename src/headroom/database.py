import logging
from collections.abc import AsyncGenerator
from datetime import timezone

from sqlalchemy import DateTime, TypeDecorator, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from headroom import config
from headroom.config import settings

logger = logging.getLogger(__name__)

# `hide_parameters`: a SQLAlchemy error renders its statement AND the bound
# values — `[parameters: ('Ab3d…',)]` — and that string reaches the traceback
# uvicorn prints and the `error.unhandled` row `error_handler` writes. A share
# token is a bound value in `WHERE share_links.token = ?`, so a database fault
# while resolving one wrote the live credential into the container log and
# into the row the backup uploads off the box. The handler formats statement
# errors from their DBAPI cause for the same reason; this flag covers every
# rendering the handler never sees.
engine = create_async_engine(settings.database_url, echo=False, hide_parameters=True)
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
    Read through `config.env_choice`, the one reader for closed-set knobs.
    """
    return config.env_choice(
        "HEADROOM_SQLITE_SYNCHRONOUS", SYNCHRONOUS_MODES, DEFAULT_SYNCHRONOUS
    )


async def checkpoint_wal(bind=None) -> None:
    """Fold the WAL back into the main database file.

    `bind` is the engine to checkpoint, defaulting to this module's. The
    lifespan passes `app.state.engine`, which is the same seam the auth gate
    and `error_handler` already use for sessions — so a test that boots the
    real lifespan checkpoints the test database rather than a `headroom.db`
    it silently created in the working directory.

    Called on graceful shutdown. `synchronous=FULL` already makes each commit
    durable, so this is not about losing transactions — it is about what a
    later power cut finds on disk. A truncated WAL means the next boot has
    nothing to replay, which is one fewer moving part in exactly the situation
    that started all of this.

    Best-effort: a failure here must not turn a clean shutdown into a crash.
    """
    bind = bind if bind is not None else engine
    if bind.dialect.name != "sqlite":
        return
    try:
        async with bind.begin() as conn:
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

        **No `PRAGMA foreign_keys`, deliberately.** SQLite enforces no foreign
        key without it, so the `REFERENCES` clauses in this schema document
        relationships and enforce nothing; the app does its own integrity work
        (`reattach_orphaned_cases`, `delete_hat` unlinking purchases, the ORM's
        delete-orphan cascades). Turning enforcement on is not a one-line
        change: every existing install would first need an orphan audit, and
        `_rebuild_hats_autoincrement` depends on it being off — with it on,
        `DROP TABLE hats` runs an implicit DELETE that fails on (or cascades
        into) every row that references a hat. The models therefore declare no
        `ondelete=` either; a clause the engine never runs is a promise the
        schema should not make.
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


class UtcDateTime(TypeDecorator):
    """A timestamp that is UTC on the way in and UTC-AWARE on the way out.

    SQLite stores no zone, so every `DateTime` column came back naive and
    pydantic serialized it without an offset — `"2026-09-06T16:32:27"` — and
    a browser reads an offset-less ISO string as LOCAL time. Measured in a
    UTC−7 browser: a password change made at 16:32 UTC rendered "4:32 PM"
    (seven hours in the future), a run started 7 h 41 min earlier read "40
    min ago", and `timeAgo` clamps at zero so every run read "just now" for
    its first seven hours. The three columns that already carried a zone
    rendered correctly beside them — inconsistent rather than uniformly
    wrong, which is the harder kind to notice.

    Bound values are normalized to naive UTC (an aware value from another
    zone is converted; a naive one is taken as UTC, which is what every
    writer in this app produces). Loaded values get `tzinfo=UTC`, so they
    serialize with an offset and compare with `datetime.now(timezone.utc)`
    without the `replace(tzinfo=...)` guards two services carry.
    `server_default=func.now()` is unaffected: SQLite's CURRENT_TIMESTAMP is
    UTC.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


# ---- migrations ------------------------------------------------------------ #
#
# Two install paths have to arrive at ONE schema. A fresh install gets every
# table from `Base.metadata.create_all`, straight off the models. An upgraded
# install already has its tables, and `create_all` only ever CREATEs — it will
# not add a column or an index to a table that exists — so everything a model
# gained after its table first shipped reaches an upgraded database through the
# static DDL below and nowhere else. SQLAlchemy SELECTs every mapped column, so
# one forgotten entry is not a degraded feature: every read of that table fails
# on every upgraded install, and on none of the machines the column was added
# on.
#
# `tests/test_schema_consistency.py` holds each table as it FIRST shipped,
# upgrades that, and compares the result with a fresh install column by column
# (type, NOT NULL, default), index by index, and AUTOINCREMENT by table. It
# covers every table in `Base.metadata` and fails when a new one appears
# without being registered, which is what makes the per-table dicts below a
# checked contract rather than a convention.
#
# Static, fully-formed DDL throughout — column names and types are hard-coded
# literals, so no interpolation is needed and SQL injection is structurally
# impossible.
#
# Every column a model declares NOT NULL has to be added here as `NOT NULL
# DEFAULT <x>` with the model carrying the same `server_default`, because
# SQLite refuses to ADD a NOT NULL column without a default. The one exception
# is `cases.room_id`, whose only possible default was the hardcoded room the
# `is_default` flag replaced (see `_CASE_COLUMN_DDL`).

# v2.4 — the fallback room became a flag instead of a hardcoded id=1. Added
# with `_ROOM_DEFAULT_BACKFILL_DML`, which flags the lowest id rather than a
# literal 1, so a database whose original room was renamed or re-keyed still
# ends up with exactly one default. `ensure_default_room()` re-checks the
# invariant on every boot.
_ROOM_COLUMN_DDL: dict[str, str] = {
    "is_default": "ALTER TABLE rooms ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT 0",
}
_ROOM_DEFAULT_BACKFILL_DML = (
    "UPDATE rooms SET is_default = 1 WHERE id = (SELECT MIN(id) FROM rooms)"
)

_PURCHASE_COLUMN_DDL: dict[str, str] = {
    # v2.19 — the size on the order line, so matching can tell two sizes of the
    # same model apart instead of binding to whichever hat comes back first.
    "size": "ALTER TABLE purchases ADD COLUMN size VARCHAR(20)",
    # What a match actually wrote onto the hat, so unmatch reverts exactly that.
    "match_writes": "ALTER TABLE purchases ADD COLUMN match_writes TEXT",
}

_CASE_COLUMN_DDL: dict[str, str] = {
    # v0.9 — per-case capacity override (NULL → type default)
    "capacity": "ALTER TABLE cases ADD COLUMN capacity INTEGER",
    # Nullable and with NO default, where this used to say `DEFAULT 1`: that
    # was the hardcoded room the `is_default` flag replaced, and it stayed in
    # the schema as a silent destination for any INSERT that forgot its room.
    # A database this old has no rooms table yet; `create_all` makes one,
    # `ensure_default_room` seeds it, and `reattach_orphaned_cases` — the last
    # step of `init_db` — moves every NULL here onto the default room. The
    # column cannot be NOT NULL (SQLite needs a default for that), so
    # `Case._require_room` is what refuses a room-less case on this install.
    "room_id": "ALTER TABLE cases ADD COLUMN room_id INTEGER REFERENCES rooms(id)",
}

_WEAR_LOG_COLUMN_DDL: dict[str, str] = {
    # What `hats.date_last_worn` held before this wear, so undoing it restores
    # a hand-typed date (see `WearLog.date_last_worn_before`). Nullable: a
    # wear logged before the column existed has no answer to give.
    "date_last_worn_before": "ALTER TABLE wear_log ADD COLUMN date_last_worn_before DATE",
}

_HAT_COLOR_COLUMN_DDL: dict[str, str] = {
    "general_color": (
        "ALTER TABLE hat_colors ADD COLUMN general_color VARCHAR(30) NOT NULL DEFAULT ''"
    ),
    "tier": "ALTER TABLE hat_colors ADD COLUMN tier VARCHAR(12) NOT NULL DEFAULT 'primary'",
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
    # Who wrote the construction ('owner' or NULL) — the construction audit's
    # bulk clear leaves an owner's value alone by this.
    "construction_source": "ALTER TABLE hats ADD COLUMN construction_source VARCHAR(20)",
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
    # No FK clause here: a table this old is rebuilt straight afterwards by
    # `_rebuild_hats_autoincrement`, whose CREATE carries the model's
    # `REFERENCES rooms (id)` — and SQLite enforces neither (see
    # `_sqlite_pragmas`); the app keeps the relationship itself.
    "direct_room_id": "ALTER TABLE hats ADD COLUMN direct_room_id INTEGER",
    # v2.33 — special/limited runs, stated by the owner.
    "limited_edition": "ALTER TABLE hats ADD COLUMN limited_edition BOOLEAN NOT NULL DEFAULT 0",
    "analysis_status": "ALTER TABLE hats ADD COLUMN analysis_status VARCHAR(20)",
    "analysis_stage": "ALTER TABLE hats ADD COLUMN analysis_stage VARCHAR(20)",
    "analysis_stage_at": "ALTER TABLE hats ADD COLUMN analysis_stage_at DATETIME",
    "analysis_job_id": "ALTER TABLE hats ADD COLUMN analysis_job_id INTEGER",
    "analysis_error": "ALTER TABLE hats ADD COLUMN analysis_error TEXT",
    # Who set the colors ('owner' or NULL) — re-analysis keeps an owner's.
    "colors_source": "ALTER TABLE hats ADD COLUMN colors_source VARCHAR(20)",
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


# Static DML for the `cancelled` → `canceled` rename; keyed by table so the
# loop that runs it never interpolates a name into SQL.
_STATUS_RENAME_DML: dict[str, str] = {
    "import_jobs": "UPDATE import_jobs SET status = 'canceled' WHERE status = 'cancelled'",
    "import_job_items": (
        "UPDATE import_job_items SET status = 'canceled' WHERE status = 'cancelled'"
    ),
    "activity_log": (
        "UPDATE activity_log SET kind = 'import.canceled' WHERE kind = 'import.cancelled'"
    ),
}


#: Every table's post-first-ship column DDL. A table with no entry has gained
#: no column since it shipped; the parity test fails the day its model does.
_COLUMN_DDL: dict[str, dict[str, str]] = {
    "rooms": _ROOM_COLUMN_DDL,
    "cases": _CASE_COLUMN_DDL,
    "hat_colors": _HAT_COLOR_COLUMN_DDL,
    "hats": _HAT_COLUMN_DDL,
    "purchases": _PURCHASE_COLUMN_DDL,
    "wear_log": _WEAR_LOG_COLUMN_DDL,
}


#: Static, like every DDL string here.
_HAT_POSITION_INDEX_DDL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_hats_case_position "
    "ON hats(case_id, position_in_case) "
    "WHERE case_id IS NOT NULL AND disposed_at IS NULL"
)

#: Indexes a model declares that an upgraded database would otherwise never
#: get: each is on a column (or a constraint) that arrived after its table
#: first shipped, and `create_all` does not index a table that already exists.
#: `analysis_job_id` came in 2.10 as a bare ALTER, so every older install was
#: running job progress — a COUNT over exactly that column — as a full scan.
#: Run after the data repairs, because two of these are UNIQUE and cannot be
#: built over the duplicates the repairs remove.
_INDEX_DDL: dict[str, tuple[str, ...]] = {
    "hats": (
        _HAT_POSITION_INDEX_DDL,
        "CREATE INDEX IF NOT EXISTS ix_hats_analysis_job_id ON hats (analysis_job_id)",
    ),
    "hat_colors": (
        "CREATE INDEX IF NOT EXISTS ix_hat_colors_general_color ON hat_colors (general_color)",
    ),
    "wear_log": (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_wear_hat_day ON wear_log(hat_id, worn_at)",
    ),
}


# ---- the one-time hats rebuild -------------------------------------------- #
#
# SQLite gives a rowid table `max(id) + 1`, so deleting the newest hat handed
# its id to the next hat created. A hat's tag is `/t/h/<id>` on a sticker that
# cannot be rewritten, so the old sticker went on scanning and opened the new
# hat. `AUTOINCREMENT` is the only fix that holds (`models/hat.py`), and SQLite
# can only add it by rebuilding the table: create the new shape, copy, drop the
# old, rename the new into place — in that order, which is SQLite's own
# documented procedure. Renaming the NEW table (never the old one) is what
# keeps the `REFERENCES hats(id)` clauses in other tables pointing at `hats`.
#
# The CREATE below is the hats schema as of the release that introduced the
# rebuild, frozen. It never needs editing: the rebuild runs after the
# `_HAT_COLUMN_DDL` pass, copies exactly these columns, and the pass runs again
# afterwards — so a column added to the model later is re-added to a freshly
# rebuilt table empty, which is all it could have held on a database that had
# never seen it. The parity test runs this path end to end.
#
# A retired column still sitting on an old install (`custom_style_detail`,
# unmapped and unread since 2.7.0) is not copied. The rolling backups predate
# the rebuild and still hold it.

_HATS_TABLE_SQL = "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'hats'"

_HATS_REBUILD_CREATE_DDL = (
    "CREATE TABLE hats_new ("
    "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
    "case_id INTEGER, "
    "position_in_case INTEGER, "
    "direct_room_id INTEGER, "
    "limited_edition BOOLEAN DEFAULT 0 NOT NULL, "
    "photo_path VARCHAR(255), "
    "original_path VARCHAR(255), "
    "thumb_path VARCHAR(255), "
    "condition VARCHAR(20) NOT NULL, "
    "date_last_worn DATE, "
    "size VARCHAR(10) NOT NULL, "
    "style VARCHAR(20) NOT NULL, "
    "is_beanie BOOLEAN NOT NULL, "
    "brand VARCHAR(80), "
    "model_name VARCHAR(120), "
    "colorway VARCHAR(120), "
    "model_confidence VARCHAR(10), "
    "style_descriptor VARCHAR(120), "
    "design_notes TEXT, "
    "owner_notes TEXT, "
    "purchase_price FLOAT, "
    "purchased_at DATETIME, "
    "construction VARCHAR(80), "
    "hydrolite BOOLEAN DEFAULT 0 NOT NULL, "
    "hydro BOOLEAN DEFAULT 0 NOT NULL, "
    "artist_series VARCHAR(160), "
    "logo_detected VARCHAR(255), "
    "analysis_status VARCHAR(20), "
    "analysis_stage VARCHAR(20), "
    "analysis_stage_at DATETIME, "
    "analysis_job_id INTEGER, "
    "analysis_error TEXT, "
    "analyzed_at DATETIME, "
    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
    "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
    "estimated_new_price FLOAT, "
    "estimated_new_price_source VARCHAR(80), "
    "resale_price FLOAT, "
    "resale_price_source VARCHAR(80), "
    "resale_price_url VARCHAR(500), "
    "resale_checked_at DATETIME, "
    "resale_price_scope VARCHAR(20), "
    "ebay_avg_price FLOAT, "
    "ebay_median_price FLOAT, "
    "ebay_listing_count INTEGER, "
    "ebay_search_url VARCHAR(500), "
    "ebay_checked_at DATETIME, "
    "disposed_at DATETIME, "
    "disposed_via VARCHAR(20), "
    "disposed_price FLOAT, "
    "disposed_to VARCHAR(120), "
    "disposed_notes TEXT, "
    "FOREIGN KEY(case_id) REFERENCES cases (id), "
    "FOREIGN KEY(direct_room_id) REFERENCES rooms (id)"
    ")"
)

#: Both column lists are the CREATE's, in its order; a test pins all three to
#: one another.
_HATS_REBUILD_COPY_DML = (
    "INSERT INTO hats_new ("
    "id, case_id, position_in_case, direct_room_id, limited_edition, photo_path, "
    "original_path, thumb_path, condition, date_last_worn, size, style, is_beanie, "
    "brand, model_name, colorway, model_confidence, style_descriptor, design_notes, "
    "owner_notes, purchase_price, purchased_at, construction, hydrolite, hydro, "
    "artist_series, logo_detected, analysis_status, analysis_stage, analysis_stage_at, "
    "analysis_job_id, analysis_error, analyzed_at, created_at, updated_at, "
    "estimated_new_price, estimated_new_price_source, resale_price, resale_price_source, "
    "resale_price_url, resale_checked_at, resale_price_scope, ebay_avg_price, "
    "ebay_median_price, ebay_listing_count, ebay_search_url, ebay_checked_at, "
    "disposed_at, disposed_via, disposed_price, disposed_to, disposed_notes"
    ") SELECT "
    "id, case_id, position_in_case, direct_room_id, limited_edition, photo_path, "
    "original_path, thumb_path, condition, date_last_worn, size, style, is_beanie, "
    "brand, model_name, colorway, model_confidence, style_descriptor, design_notes, "
    "owner_notes, purchase_price, purchased_at, construction, hydrolite, hydro, "
    "artist_series, logo_detected, analysis_status, analysis_stage, analysis_stage_at, "
    "analysis_job_id, analysis_error, analyzed_at, created_at, updated_at, "
    "estimated_new_price, estimated_new_price_source, resale_price, resale_price_source, "
    "resale_price_url, resale_checked_at, resale_price_scope, ebay_avg_price, "
    "ebay_median_price, ebay_listing_count, ebay_search_url, ebay_checked_at, "
    "disposed_at, disposed_via, disposed_price, disposed_to, disposed_notes"
    " FROM hats"
)

#: Where an id this database has ALREADY handed out can still be seen. The
#: rebuild seeds AUTOINCREMENT past all of them, not just past the hats that
#: survive: a hat deleted last week was the newest, its id is on a sticker,
#: and `MAX(hats.id)` alone would hand that id straight back. `activity_log`
#: records every `hat.created` / `hat.deleted` (for the retention window) and
#: import items keep the id of the hat they made. Keyed by table so only tables
#: this database has are queried, and nothing is interpolated.
_HAT_ID_HIGH_WATER_SQL: dict[str, str] = {
    "hats": "SELECT MAX(id) FROM hats",
    "hat_colors": "SELECT MAX(hat_id) FROM hat_colors",
    "wear_log": "SELECT MAX(hat_id) FROM wear_log",
    "purchases": "SELECT MAX(hat_id) FROM purchases",
    "import_job_items": "SELECT MAX(hat_id) FROM import_job_items",
    "activity_log": "SELECT MAX(entity_id) FROM activity_log WHERE entity_type = 'hat'",
}


def _repair_duplicate_positions(conn) -> int:
    """Renumber the active hats of any case where two share a position.

    Before the placement lock, concurrent assigns could land several hats on
    one slot. Those rows are real hats; only their positions are wrong. Each
    affected case is renumbered 1..n in (position, id) order, so a hat that
    already sat alone at a low slot keeps it and the duplicates fan out
    upward. Returns the number of hats moved. Idempotent.
    """
    dupes = conn.execute(text(
        "SELECT DISTINCT case_id FROM hats "
        "WHERE case_id IS NOT NULL AND disposed_at IS NULL AND position_in_case IS NOT NULL "
        "GROUP BY case_id, position_in_case HAVING COUNT(*) > 1"
    )).scalars().all()
    moved = 0
    for case_id in dupes:
        rows = conn.execute(text(
            "SELECT id, position_in_case FROM hats "
            "WHERE case_id = :case_id AND disposed_at IS NULL "
            "ORDER BY position_in_case, id"
        ), {"case_id": case_id}).all()
        for new_position, (hat_id, old_position) in enumerate(rows, start=1):
            if old_position != new_position:
                conn.execute(
                    text("UPDATE hats SET position_in_case = :p WHERE id = :id"),
                    {"p": new_position, "id": hat_id},
                )
                moved += 1
    if moved:
        logger.warning(
            "Renumbered %d hat(s) in %d case(s) that shared a position", moved, len(dupes)
        )
    return moved


def _add_missing_columns(conn, table: str) -> set[str]:
    """Run `table`'s column DDL for every column it lacks. Returns those added.

    Inspects afresh each call: an `Inspector` caches its reflection, and this
    runs twice on `hats` with a table rebuild in between.
    """
    existing = {c["name"] for c in inspect(conn).get_columns(table)}
    added: set[str] = set()
    for column, ddl in _COLUMN_DDL[table].items():
        if column not in existing:
            conn.execute(text(ddl))
            added.add(column)
    return added


def _recover_interrupted_hats_rebuild(conn) -> None:
    """Finish or undo a `_rebuild_hats_autoincrement` a power cut interrupted.

    The pysqlite driver does not wrap DDL in the transaction `engine.begin()`
    opens — each CREATE/DROP/ALTER commits on its own unless a DML statement
    has already started one — so the rebuild cannot rely on being atomic. It
    is ordered so every intermediate state is one of two, and both are
    recoverable here, before anything else looks at `hats`:

      * `hats_new` beside `hats` — died before the swap; `hats` is intact and
        `hats_new` a partial copy. Drop it; the rebuild runs again.
      * `hats_new` and no `hats` — died between DROP and RENAME; the copy (a
        single INSERT, which is atomic) completed before `hats` was dropped.
        Rename it into place.
    """
    tables = set(inspect(conn).get_table_names())
    if "hats_new" not in tables:
        return
    if "hats" in tables:
        conn.execute(text("DROP TABLE hats_new"))
        logger.warning("Discarded a partial hats rebuild; it will be redone")
    else:
        conn.execute(text("ALTER TABLE hats_new RENAME TO hats"))
        logger.warning("Completed a hats rebuild that was interrupted after the copy")


def _hat_id_high_water(conn, tables: set[str]) -> int:
    """The largest hat id this database has ever shown anywhere it can still see."""
    highest = 0
    for table, sql in _HAT_ID_HIGH_WATER_SQL.items():
        if table in tables:
            highest = max(highest, conn.execute(text(sql)).scalar() or 0)
    return highest


def _rebuild_hats_autoincrement(conn) -> bool:
    """Give an existing `hats` table AUTOINCREMENT, once. True if it rebuilt.

    Skipped (False) when the table already has it — every fresh install and
    every install that has run this — and, with an ERROR in the log, in the
    two cases where going ahead could lose data instead of protecting it:

      * foreign keys are being enforced, so the DROP would cascade into (or
        fail on) every row referencing a hat;
      * a row does not fit the model's constraints (a NULL where the model
        says NOT NULL), so the copy fails. The table is left exactly as it
        was; ids stay reusable there, as they always were, rather than the
        boot failing — a boot that fails on an upgraded database is the worst
        outcome on offer, and it would fail again on every restart.
    """
    table_sql = conn.execute(text(_HATS_TABLE_SQL)).scalar()
    if table_sql is None or "AUTOINCREMENT" in table_sql.upper():
        return False
    if conn.execute(text("PRAGMA foreign_keys")).scalar():
        logger.error(
            "Not rebuilding hats for AUTOINCREMENT: PRAGMA foreign_keys is on, "
            "and dropping the old table would reach every row that references it"
        )
        return False

    high_water = _hat_id_high_water(conn, set(inspect(conn).get_table_names()))
    conn.execute(text(_HATS_REBUILD_CREATE_DDL))
    try:
        conn.execute(text(_HATS_REBUILD_COPY_DML))
    except IntegrityError as exc:
        conn.execute(text("DROP TABLE hats_new"))
        logger.error(
            "Not rebuilding hats for AUTOINCREMENT: an existing row does not fit "
            "the current schema (%s). Hat ids on this install can still be reused.",
            exc.orig,
        )
        return False
    # Seed the sequence BEFORE the swap, so a crash after it never leaves a
    # rebuilt table that would hand out a deleted hat's id. `RENAME` carries
    # the sqlite_sequence row across with the table.
    conn.execute(text("DELETE FROM sqlite_sequence WHERE name = 'hats_new'"))
    conn.execute(
        text("INSERT INTO sqlite_sequence (name, seq) VALUES ('hats_new', :seq)"),
        {"seq": high_water},
    )
    conn.execute(text("DROP TABLE hats"))
    conn.execute(text("ALTER TABLE hats_new RENAME TO hats"))
    logger.warning(
        "Rebuilt hats with AUTOINCREMENT; new hat ids start after %d", high_water
    )
    return True


def _run_migrations(conn) -> None:
    """Bring an EXISTING database's tables up to the models.

    Creates nothing: on a fresh database this finds no tables and does
    nothing, and `Base.metadata.create_all` (run next by `init_db`) builds
    every table straight from its model. `rooms` and `app_settings` used to be
    CREATEd by hand here, which made `create_all` skip them — so a fresh
    install got the hand-written DDL instead of the model, and a column added
    to `AppSetting` would have been missing on every new install with nothing
    to catch it. One definition per table now: the model.
    """
    _recover_interrupted_hats_rebuild(conn)
    existing_tables = set(inspect(conn).get_table_names())

    if "rooms" in existing_tables:
        if "is_default" in _add_missing_columns(conn, "rooms"):
            conn.execute(text(_ROOM_DEFAULT_BACKFILL_DML))

    if "cases" in existing_tables:
        _add_missing_columns(conn, "cases")

    if "hat_colors" in existing_tables:
        _add_missing_columns(conn, "hat_colors")

    if "wear_log" in existing_tables:
        _add_missing_columns(conn, "wear_log")
        # One wear per hat per day, on tables created before the constraint:
        # dedupe (keep the earliest) so `uq_wear_hat_day` below can be built.
        conn.execute(
            text(
                "DELETE FROM wear_log WHERE id NOT IN "
                "(SELECT MIN(id) FROM wear_log GROUP BY hat_id, worn_at)"
            )
        )

    if "hats" in existing_tables:
        conn.execute(
            text("UPDATE hats SET size = 'classic' WHERE size = 'standard'")
        )
        _add_missing_columns(conn, "hats")
        _backfill_construction(conn)
        if _rebuild_hats_autoincrement(conn):
            # Columns newer than the rebuild's frozen CREATE come back here.
            _add_missing_columns(conn, "hats")
        # MUST precede `ux_hats_case_position` in `_INDEX_DDL`: a unique index
        # cannot be built over the duplicates the pre-lock race left behind.
        _repair_duplicate_positions(conn)

    if "purchases" in existing_tables:
        _add_missing_columns(conn, "purchases")

    for table, statements in _INDEX_DDL.items():
        if table in existing_tables:
            for ddl in statements:
                conn.execute(text(ddl))

    # v2.78 — the import job/item status `cancelled` became `canceled`. It is
    # a value this app invented (unlike "Heather Grey", which is melin's), it
    # is rendered raw as a badge, and the owner's rule is American spelling
    # everywhere. Static, idempotent DML: a box already migrated matches no
    # rows. The activity kind moves with it so the log does not carry two
    # spellings of one event.
    for table, dml in _STATUS_RENAME_DML.items():
        if table in existing_tables:
            conn.execute(text(dml))


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


async def ensure_default_room(session_factory=None) -> None:
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
    async with (session_factory or async_session)() as db:
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


async def reattach_orphaned_cases(session_factory=None) -> None:
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
    async with (session_factory or async_session)() as db:
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
    # repair runs in its own. Guarantees the subquery below resolves. The
    # factory is forwarded: a seam that is taken at the door and dropped one
    # call in is the exact shape the test guard exists to catch, and did.
    await ensure_default_room(session_factory)
    async with (session_factory or async_session)() as db:
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


async def init_db(bind=None, session_factory=None) -> None:
    """Migrate, create, and repair invariants — on the given engine.

    Both parameters default to this module's globals, so production is
    unchanged. They exist so the lifespan can be booted against the test
    database: until it could, the lifespan was the one part of the app no test
    ever ran, and the wiring it does — which loops start, which backfills run,
    what the health records are seeded with — was unverified while every
    function it calls had its own tests. Function tested, wiring untested.
    """
    from headroom.models import __all_models__  # noqa: PLC0415 — models import `Base` from here; a top-level import is a cycle

    _ = __all_models__  # ensure models are registered
    bind = bind if bind is not None else engine

    async with bind.begin() as conn:
        await conn.run_sync(_run_migrations)

    async with bind.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await ensure_default_room(session_factory)
    await reattach_orphaned_cases(session_factory)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
