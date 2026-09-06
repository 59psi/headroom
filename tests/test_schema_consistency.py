"""Guard the roll-forward-only migration convention with a real invariant.

The Hat model grows columns over time; each must also land in
`database._HAT_COLUMN_DDL` or an already-deployed database will be missing it
after upgrade — and because SQLAlchemy SELECTs every mapped column, ONE
forgotten entry bricks every `Hat` read on that DB (total outage, not a
degraded feature). This test simulates a legacy DB carrying only the original
structural columns, runs the migration, and asserts every model column is
present — converting the CLAUDE.md convention into an enforced invariant
(R11 — see docs/AUDIT-HISTORY.md).
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


# The columns in the first `purchases` CREATE TABLE. Anything added later must
# come from _PURCHASE_COLUMN_DDL, for the same reason as the hats list above:
# `Base.metadata.create_all` only CREATEs, so it will not add a column to a
# table an existing install already has.
_ORIGINAL_PURCHASE_COLUMNS = (
    "id INTEGER PRIMARY KEY AUTOINCREMENT",
    "source VARCHAR(20)",
    "order_ref VARCHAR(80)",
    "order_date DATETIME",
    "item_title VARCHAR(200)",
    "model_name VARCHAR(120)",
    "colorway VARCHAR(120)",
    "price FLOAT",
    "quantity INTEGER",
    "raw TEXT",
    "hat_id INTEGER",
    "created_at DATETIME",
)


async def test_purchase_migration_ddl_covers_every_model_column():
    """Same invariant as the hats one, and the same failure if it lapses.

    SQLAlchemy SELECTs every mapped column, so one column in the model with no
    DDL entry means every purchase read raises on an upgraded database — the
    Settings purchase list and the whole cost-basis matcher, dead, on installs
    that upgraded rather than on the machine the column was added on.
    """
    from headroom.models.catalog import Purchase

    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(f"CREATE TABLE purchases ({', '.join(_ORIGINAL_PURCHASE_COLUMNS)})")
            )
            _run_migrations(conn)
            migrated = {c["name"] for c in inspect(conn).get_columns("purchases")}
    finally:
        engine.dispose()

    missing = set(Purchase.__table__.columns.keys()) - migrated
    assert not missing, (
        "Purchase model columns absent from _PURCHASE_COLUMN_DDL — an upgraded "
        f"database would be missing these and every purchase read would fail: "
        f"{sorted(missing)}"
    )


# The first `cases` and `hat_colors` CREATE TABLEs. These two tables had
# hand-written `if "x" not in columns` migrations and NO parity test, so a
# column added to either model was guarded by nothing — the exact gap the two
# tests above exist to close for hats and purchases.
_ORIGINAL_CASE_COLUMNS = (
    "id INTEGER PRIMARY KEY AUTOINCREMENT",
    "case_type VARCHAR(12)",
    "sequence_number INTEGER",
    "display_id VARCHAR(10)",
    "photo_path VARCHAR(255)",
    "created_at DATETIME",
    "updated_at DATETIME",
)

_ORIGINAL_HAT_COLOR_COLUMNS = (
    "id INTEGER PRIMARY KEY AUTOINCREMENT",
    "hat_id INTEGER",
    "color_name VARCHAR(50)",
    "hex_value VARCHAR(7)",
    "dominance_rank INTEGER",
)


@pytest.mark.parametrize(
    ("table", "original", "model_path"),
    [
        ("cases", _ORIGINAL_CASE_COLUMNS, "headroom.models.case:Case"),
        ("hat_colors", _ORIGINAL_HAT_COLOR_COLUMNS, "headroom.models.hat_color:HatColor"),
    ],
)
async def test_case_and_hat_color_migrations_cover_every_model_column(table, original, model_path):
    """Same invariant, same total-outage failure mode, for the two tables that
    used to be migrated by hand: every model column must exist after the
    migration runs against the table as it first shipped."""
    import importlib

    module_name, class_name = model_path.split(":")
    model = getattr(importlib.import_module(module_name), class_name)

    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE rooms (id INTEGER PRIMARY KEY, name VARCHAR(100))"))
            conn.execute(text(f"CREATE TABLE {table} ({', '.join(original)})"))
            _run_migrations(conn)
            migrated = {c["name"] for c in inspect(conn).get_columns(table)}
    finally:
        engine.dispose()

    missing = set(model.__table__.columns.keys()) - migrated
    assert not missing, (
        f"{class_name} model columns absent from the {table} column DDL — an upgraded "
        f"database would be missing these and every read would fail: {sorted(missing)}"
    )


async def test_the_import_status_rename_migrates_stored_rows():
    """`cancelled` → `canceled` is a rename of a PERSISTED value, so an upgraded
    database must come out speaking the new spelling everywhere the old one was
    stored: both status columns and the activity kind. Idempotent — running the
    migration twice changes nothing more."""
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE rooms (id INTEGER PRIMARY KEY, name VARCHAR(100))"))
            conn.execute(text("CREATE TABLE import_jobs (id INTEGER PRIMARY KEY, status VARCHAR(20))"))
            conn.execute(
                text("CREATE TABLE import_job_items (id INTEGER PRIMARY KEY, status VARCHAR(20))")
            )
            conn.execute(text("CREATE TABLE activity_log (id INTEGER PRIMARY KEY, kind VARCHAR(60))"))
            conn.execute(text("INSERT INTO import_jobs (status) VALUES ('cancelled'), ('done')"))
            conn.execute(
                text("INSERT INTO import_job_items (status) VALUES ('cancelled'), ('queued')")
            )
            conn.execute(
                text("INSERT INTO activity_log (kind) VALUES ('import.cancelled'), ('import.created')")
            )
            _run_migrations(conn)
            _run_migrations(conn)
            jobs = [r[0] for r in conn.execute(text("SELECT status FROM import_jobs ORDER BY id"))]
            items = [r[0] for r in conn.execute(text("SELECT status FROM import_job_items ORDER BY id"))]
            kinds = [r[0] for r in conn.execute(text("SELECT kind FROM activity_log ORDER BY id"))]
    finally:
        engine.dispose()

    assert jobs == ["canceled", "done"]
    assert items == ["canceled", "queued"]
    assert kinds == ["import.canceled", "import.created"]


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
