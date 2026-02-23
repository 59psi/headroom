from collections.abc import AsyncGenerator

from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from headroom.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _run_migrations(conn) -> None:
    """Add missing tables and columns to existing databases."""
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    # Create rooms table if it doesn't exist yet
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

    # Add room_id column to cases if missing
    if "cases" in existing_tables:
        columns = [c["name"] for c in inspector.get_columns("cases")]
        if "room_id" not in columns:
            conn.execute(
                text("ALTER TABLE cases ADD COLUMN room_id INTEGER DEFAULT 1 REFERENCES rooms(id)")
            )

    # Add general_color column to hat_colors if missing
    if "hat_colors" in existing_tables:
        columns = [c["name"] for c in inspector.get_columns("hat_colors")]
        if "general_color" not in columns:
            conn.execute(
                text("ALTER TABLE hat_colors ADD COLUMN general_color VARCHAR(30) DEFAULT ''")
            )

    # Rename size 'standard' -> 'classic' in hats (schema rename)
    if "hats" in existing_tables:
        conn.execute(
            text("UPDATE hats SET size = 'classic' WHERE size = 'standard'")
        )


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

    # Run migrations for existing databases before create_all
    async with engine.begin() as conn:
        await conn.run_sync(_run_migrations)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await ensure_default_room()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
