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
