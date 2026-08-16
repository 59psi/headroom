"""Guard the roll-forward-only migration convention with a real invariant.

The Hat model grows columns over time; each must also land in
`database._HAT_COLUMN_DDL` or an already-deployed database will be missing it
after upgrade — and because SQLAlchemy SELECTs every mapped column, ONE
forgotten entry bricks every `Hat` read on that DB (total outage, not a
degraded feature). This test simulates a legacy DB carrying only the original
structural columns, runs the migration, and asserts every model column is
present — converting the CLAUDE.md convention into an enforced invariant (R11).
"""

import pytest
from sqlalchemy import create_engine, inspect, text

from headroom.database import _run_migrations
from headroom.models.hat import Hat

pytestmark = pytest.mark.anyio

# The columns present in the very first `hats` CREATE TABLE — everything NOT in
# this set must be added by _HAT_COLUMN_DDL for an old DB to reach the current
# schema. Keep this list frozen; new columns belong in the migration DDL.
_ORIGINAL_HAT_COLUMNS = (
    "id INTEGER PRIMARY KEY AUTOINCREMENT",
    "case_id INTEGER",
    "position_in_case INTEGER",
    "photo_path VARCHAR(255)",
    "condition VARCHAR(20)",
    "date_last_worn DATE",
    "size VARCHAR(10)",
    "style VARCHAR(20)",
    "is_beanie BOOLEAN",
    "created_at DATETIME",
    "updated_at DATETIME",
)


async def test_hat_migration_ddl_covers_every_model_column():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(text(f"CREATE TABLE hats ({', '.join(_ORIGINAL_HAT_COLUMNS)})"))
            _run_migrations(conn)
            migrated = {c["name"] for c in inspect(conn).get_columns("hats")}
    finally:
        engine.dispose()

    model_columns = set(Hat.__table__.columns.keys())
    missing = model_columns - migrated
    assert not missing, (
        "Hat model columns absent from _HAT_COLUMN_DDL — an upgraded database "
        f"would be missing these and every hat read would fail: {sorted(missing)}"
    )


async def test_rooms_migration_backfills_exactly_one_default():
    """An upgraded DB must end up with exactly one room flagged is_default.

    The flag replaced a hardcoded `room_id == 1`, so the backfill deliberately
    keys on MIN(id) rather than the literal 1 — a database whose original room
    was deleted or re-keyed still has to come out with a usable fallback, or
    case creation and room deletion both break on the upgraded install.
    """
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(
                text("CREATE TABLE rooms (id INTEGER PRIMARY KEY, name VARCHAR(100))")
            )
            # Note: no room with id 1 — the pre-flag code would have had nothing
            # to fall back on here.
            conn.execute(text("INSERT INTO rooms (id, name) VALUES (3, 'Office'), (7, 'Attic')"))
            _run_migrations(conn)
            rows = conn.execute(
                text("SELECT id, is_default FROM rooms ORDER BY id")
            ).all()
    finally:
        engine.dispose()

    flagged = [r[0] for r in rows if r[1]]
    assert flagged == [3], f"expected only the lowest id flagged, got {rows}"


async def test_fresh_database_rooms_table_matches_the_model():
    """`_run_migrations` CREATEs `rooms` itself, which makes `create_all` a no-op
    for that table — so the hand-written DDL, not the model, is what a brand new
    install actually gets. If the two drift, the container crashes on first boot
    (this exact gap shipped a rooms table with no is_default and 500'd startup).
    """
    from headroom.models.room import Room

    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            _run_migrations(conn)  # empty DB, as on a first run
            created = {c["name"] for c in inspect(conn).get_columns("rooms")}
    finally:
        engine.dispose()

    missing = set(Room.__table__.columns.keys()) - created
    assert not missing, (
        "Room model columns absent from the CREATE TABLE in _run_migrations — a "
        f"fresh install would crash on boot: {sorted(missing)}"
    )
