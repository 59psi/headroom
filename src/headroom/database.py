from collections.abc import AsyncGenerator

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from headroom.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


if engine.dialect.name == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - connect hook
        """Tune SQLite for a multi-writer single-process app on a Pi.

        WAL lets readers proceed during a write; busy_timeout makes writers
        wait out a lock instead of raising 'database is locked' immediately —
        directly shrinking the transient-lock error class that could otherwise
        surface on the import worker and background loops.
        """
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA synchronous=NORMAL")
        finally:
            cur.close()


class Base(DeclarativeBase):
    pass


# Static, fully-formed DDL — column names and types are hard-coded literals,
# so no interpolation is needed and SQL injection is structurally impossible.
_HAT_COLUMN_DDL: dict[str, str] = {
    "custom_style_detail": "ALTER TABLE hats ADD COLUMN custom_style_detail VARCHAR(255)",
    "brand": "ALTER TABLE hats ADD COLUMN brand VARCHAR(80)",
    "model_name": "ALTER TABLE hats ADD COLUMN model_name VARCHAR(120)",
    "model_confidence": "ALTER TABLE hats ADD COLUMN model_confidence VARCHAR(10)",
    "style_descriptor": "ALTER TABLE hats ADD COLUMN style_descriptor VARCHAR(120)",
    "design_notes": "ALTER TABLE hats ADD COLUMN design_notes TEXT",
    "estimated_new_price": "ALTER TABLE hats ADD COLUMN estimated_new_price FLOAT",
    "estimated_new_price_source": "ALTER TABLE hats ADD COLUMN estimated_new_price_source VARCHAR(80)",
    "resale_price": "ALTER TABLE hats ADD COLUMN resale_price FLOAT",
    "resale_price_source": "ALTER TABLE hats ADD COLUMN resale_price_source VARCHAR(80)",
    "resale_price_url": "ALTER TABLE hats ADD COLUMN resale_price_url VARCHAR(500)",
    "resale_checked_at": "ALTER TABLE hats ADD COLUMN resale_checked_at DATETIME",
    "analysis_status": "ALTER TABLE hats ADD COLUMN analysis_status VARCHAR(20)",
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


async def ensure_default_room() -> None:
    """Seed the default room using raw SQL to avoid cascading relationship loads."""
    async with async_session() as db:
        result = await db.execute(text("SELECT id FROM rooms WHERE id = 1"))
        if not result.scalar_one_or_none():
            await db.execute(
                text("INSERT INTO rooms (id, name) VALUES (1, 'Default Room')")
            )
            await db.commit()


async def init_db() -> None:
    from headroom.models import __all_models__  # noqa: F811

    _ = __all_models__  # ensure models are registered

    async with engine.begin() as conn:
        await conn.run_sync(_run_migrations)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await ensure_default_room()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
