"""Two install paths, one schema — checked for every table, not five of them.

A fresh install gets its tables from `Base.metadata.create_all`, straight off
the models. An upgraded install already has its tables, and `create_all` never
alters one, so everything a model gained since its table first shipped reaches
that database through `database._run_migrations` and nowhere else. SQLAlchemy
SELECTs every mapped column: one column in a model with no migration behind it
bricks every read of that table on every upgraded install — and on none of
the machines where it was added.

This guard used to be five hand-picked tables (hats, purchases, cases,
hat_colors, rooms) checked for column NAMES only. A column added to
`AppSetting` or `ImportJob` shipped green; `ix_hats_analysis_job_id` never
reached a database older than 2.10; `hats.limited_edition` was NOT NULL with a
default on one path and without it on the other. So now:

* `_FIRST_SHIPPED` records every table as it FIRST shipped — its columns, its
  indexes, and whether it had AUTOINCREMENT; the two `_run_migrations` used to
  CREATE by hand (`rooms`, `app_settings`) are built from that exact DDL, not
  from a tidied copy of the model. Frozen: a table's first shape never
  changes, and a table that is not listed fails the test.
* The legacy database is built from those shapes, upgraded the way `init_db`
  upgrades (migrations, then `create_all`, twice — a second boot must be a
  no-op), and compared with a fresh install: every column's type, NOT NULL,
  default and primary-key flag; every index (by columns, uniqueness and
  partial predicate, so a named index and a UNIQUE constraint count alike);
  and AUTOINCREMENT, table by table.

A new column needs its `ALTER` in `database._COLUMN_DDL`; a new index on a
later column needs its `CREATE INDEX` in `database._INDEX_DDL`; a new table
needs an entry here with the columns it ships with. The failure message says
which.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import pytest
from sqlalchemy import (
    Column,
    Index,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)

from headroom import database
from headroom.database import Base, _run_migrations
from headroom.models import __all_models__

pytestmark = pytest.mark.anyio

_ = __all_models__  # every model registered on Base.metadata


@dataclass(frozen=True)
class FirstShipped:
    """A table as its first release created it."""

    columns: frozenset[str]
    #: Names of the indexes AND named UNIQUE constraints it shipped with.
    indexes: frozenset[str] = frozenset()
    autoincrement: bool = False
    #: Columns an old install still carries that no model maps any more.
    retired: tuple[tuple[str, object], ...] = field(default=())
    #: The literal CREATE a table was made with when `_run_migrations` wrote it
    #: by hand rather than `create_all` building it from the model. Those
    #: installs have THIS table, NOT NULLs and all, not an idealized copy of
    #: the model cut down to the first columns — and an upgraded install is
    #: compared as it really is.
    hand_ddl: str | None = None


def _cols(*names: str) -> frozenset[str]:
    return frozenset(names)


_FIRST_SHIPPED: dict[str, FirstShipped] = {
    # The initial commit.
    "hats": FirstShipped(
        _cols(
            "id", "case_id", "position_in_case", "photo_path", "condition",
            "date_last_worn", "size", "style", "is_beanie", "created_at", "updated_at",
        ),
        # Unmapped since 2.7.0 and never dropped; an old install still has it.
        retired=(("custom_style_detail", String(255)),),
    ),
    "cases": FirstShipped(
        _cols(
            "id", "case_type", "sequence_number", "display_id", "photo_path",
            "created_at", "updated_at",
        ),
        frozenset({"ix_cases_display_id"}),
    ),
    "hat_colors": FirstShipped(
        _cols("id", "hat_id", "color_name", "hex_value", "dominance_rank"),
        frozenset({"ix_hat_colors_color_name"}),
    ),
    # Both hand-created by `_run_migrations` until 2.81, and these are the
    # statements that did it (a551d6e, b1ea3f8) — `is_default` came later.
    "rooms": FirstShipped(
        _cols("id", "name", "created_at", "updated_at"), autoincrement=True,
        hand_ddl=(
            "CREATE TABLE rooms ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  name VARCHAR(100) UNIQUE NOT NULL,"
            "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
            "  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"
            ")"
        ),
    ),
    "app_settings": FirstShipped(
        _cols("key", "value", "updated_at"),
        hand_ddl=(
            "CREATE TABLE app_settings ("
            "  key VARCHAR(64) PRIMARY KEY,"
            "  value TEXT,"
            "  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"
            ")"
        ),
    ),
    # v1.1
    "colorway_catalog": FirstShipped(
        _cols(
            "id", "title", "model_name", "colorway", "category", "listing_count",
            "first_seen", "last_seen",
        ),
        frozenset({
            "ix_colorway_catalog_title", "ix_colorway_catalog_model_name",
            "ix_colorway_catalog_colorway",
        }),
    ),
    "purchases": FirstShipped(
        _cols(
            "id", "source", "order_ref", "order_date", "item_title", "model_name",
            "colorway", "price", "quantity", "raw", "hat_id", "created_at",
        ),
        frozenset({"ix_purchases_model_name", "ix_purchases_hat_id"}),
    ),
    # v1.2 — without the one-wear-per-day constraint, which came later.
    "wear_log": FirstShipped(
        _cols("id", "hat_id", "worn_at", "created_at"),
        frozenset({"ix_wear_log_hat_id"}),
    ),
    "activity_log": FirstShipped(
        _cols("id", "occurred_at", "kind", "entity_type", "entity_id", "summary", "details"),
        frozenset({
            "ix_activity_log_entity_id", "ix_activity_log_entity_type",
            "ix_activity_log_kind", "ix_activity_log_occurred_at",
        }),
    ),
    "import_jobs": FirstShipped(
        _cols(
            "id", "created_at", "finished_at", "total", "done", "errors", "skipped",
            "status", "defaults_json",
        ),
    ),
    "import_job_items": FirstShipped(
        _cols("id", "job_id", "filename", "status", "hat_id", "error", "bytes", "staged_path"),
        frozenset({"ix_import_job_items_job_id"}),
    ),
    "analysis_jobs": FirstShipped(_cols("id", "started_at", "finished_at", "total", "status")),
    "users": FirstShipped(
        _cols("id", "username", "password_hash", "api_token", "created_at"),
        frozenset({"ix_users_username", "ix_users_api_token"}),
    ),
    "auth_sessions": FirstShipped(
        _cols("id", "user_id", "created_at", "expires_at"),
        frozenset({"ix_auth_sessions_user_id"}),
    ),
    "passkey_credentials": FirstShipped(
        _cols("id", "user_id", "credential_id", "public_key", "sign_count", "name", "created_at"),
        frozenset({"ix_passkey_credentials_credential_id", "ix_passkey_credentials_user_id"}),
    ),
    "share_links": FirstShipped(
        _cols("id", "token", "label", "created_at", "expires_at", "revoked_at"),
        frozenset({"ix_share_links_token"}),
    ),
}

#: (table, column) pairs allowed to differ in NOT NULL only, each for a reason
#: the schema cannot express — SQLite cannot add NOT NULL to a column that
#: already exists, short of rebuilding the table:
#:
#: * `cases.room_id` — SQLite refuses to ADD a NOT NULL column without a
#:   default, and its only possible default was the hardcoded room the
#:   `is_default` flag replaced; `Case._require_room` enforces it instead.
#: * The hand-written `rooms` and `app_settings` (see `hand_ddl`) never said
#:   NOT NULL on their keys or timestamps. Every writer is the ORM, which
#:   supplies all five, and none of them is read as possibly-NULL.
_NOT_NULL_EXEMPT = {
    ("cases", "room_id"),
    ("rooms", "id"),
    ("rooms", "created_at"),
    ("rooms", "updated_at"),
    ("app_settings", "key"),
    ("app_settings", "updated_at"),
}


def _create_legacy(conn) -> None:
    """A pre-2.81 database: every model table in the shape it first shipped."""
    _legacy_metadata().create_all(conn)
    for spec in _FIRST_SHIPPED.values():
        if spec.hand_ddl is not None:
            conn.execute(text(spec.hand_ddl))


def _legacy_metadata() -> MetaData:
    """Every model-built table, cut back to the shape it first shipped in.

    The hand-created tables are not here; `_create_legacy` runs their DDL.
    """
    md = MetaData()
    for model_table in Base.metadata.sorted_tables:
        spec = _FIRST_SHIPPED[model_table.name]
        if spec.hand_ddl is not None:
            continue
        columns = [
            Column(
                c.name, c.type,
                primary_key=c.primary_key,
                nullable=c.nullable,
                server_default=c.server_default.arg if c.server_default is not None else None,
                unique=True if (c.unique and not c.index) else None,
            )
            for c in model_table.columns if c.name in spec.columns
        ]
        columns += [Column(name, type_) for name, type_ in spec.retired]
        legacy = Table(
            model_table.name, md, *columns, sqlite_autoincrement=spec.autoincrement
        )
        for idx in model_table.indexes:
            if idx.name in spec.indexes:
                Index(
                    idx.name, *[legacy.c[col.name] for col in idx.columns],
                    unique=idx.unique, **idx.dialect_kwargs,
                )
        for constraint in model_table.constraints:
            if isinstance(constraint, UniqueConstraint) and constraint.name in spec.indexes:
                legacy.append_constraint(UniqueConstraint(
                    *[col.name for col in constraint.columns], name=constraint.name
                ))
    return md


def _boot(conn) -> None:
    """What `init_db` does to the schema, twice: a second boot must be a no-op."""
    for _ in range(2):
        _run_migrations(conn)
        Base.metadata.create_all(conn)


def _where(index: dict) -> str:
    """A partial index's predicate, whitespace-normalized ("" for none)."""
    where = index.get("dialect_options", {}).get("sqlite_where")
    return "" if where is None else re.sub(r"\s+", " ", str(where)).strip()


def _snapshot(conn) -> dict[str, dict]:
    insp = inspect(conn)
    out: dict[str, dict] = {}
    for table in insp.get_table_names():
        columns = {
            c["name"]: (
                str(c["type"]), bool(c["nullable"]),
                None if c["default"] is None else str(c["default"]), bool(c["primary_key"]),
            )
            for c in insp.get_columns(table)
        }
        # `include_auto_indexes`: an inline `name ... UNIQUE` (the hand-written
        # `rooms`) is an automatic index and no named constraint, so without
        # it the uniqueness is invisible to reflection on one path only.
        indexes = {
            (tuple(i["column_names"]), bool(i["unique"]), _where(i))
            for i in insp.get_indexes(table, include_auto_indexes=True)
        } | {
            (tuple(u["column_names"]), True, "")
            for u in insp.get_unique_constraints(table)
        }
        sql = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :t"), {"t": table}
        ).scalar()
        out[table] = {
            "columns": columns,
            "indexes": indexes,
            "autoincrement": "AUTOINCREMENT" in sql.upper(),
        }
    return out


def _fresh_and_upgraded() -> tuple[dict, dict]:
    fresh_engine = create_engine("sqlite://")
    upgraded_engine = create_engine("sqlite://")
    try:
        with fresh_engine.begin() as conn:
            _boot(conn)
            fresh = _snapshot(conn)
        with upgraded_engine.begin() as conn:
            _create_legacy(conn)
            _boot(conn)
            upgraded = _snapshot(conn)
    finally:
        fresh_engine.dispose()
        upgraded_engine.dispose()
    return fresh, upgraded


async def test_every_table_is_registered_with_its_first_shape():
    """A table missing here is a table nothing checks — register what it ships with."""
    missing = sorted(set(Base.metadata.tables) - set(_FIRST_SHIPPED))
    stale = sorted(set(_FIRST_SHIPPED) - set(Base.metadata.tables))
    assert not missing, f"add these to _FIRST_SHIPPED with their current columns: {missing}"
    assert not stale, f"no longer a model table: {stale}"


async def test_an_upgraded_database_has_every_model_column():
    """The total-outage class: a model column an upgraded database lacks."""
    _, upgraded = _fresh_and_upgraded()
    for table in Base.metadata.sorted_tables:
        missing = set(table.columns.keys()) - set(upgraded[table.name]["columns"])
        assert not missing, (
            f"{table.name}: model columns with no ALTER in database._COLUMN_DDL — every "
            f"read of this table fails on an upgraded install: {sorted(missing)}"
        )


async def test_a_fresh_database_has_every_model_column():
    """The other install path. `rooms` and `app_settings` used to be CREATEd by
    hand in `_run_migrations`, which made `create_all` skip them, so a fresh
    install got the hand-written DDL instead of the model."""
    fresh, _ = _fresh_and_upgraded()
    for table in Base.metadata.sorted_tables:
        missing = set(table.columns.keys()) - set(fresh[table.name]["columns"])
        assert not missing, f"{table.name}: fresh install is missing {sorted(missing)}"


async def test_fresh_and_upgraded_columns_agree_on_type_null_and_default():
    fresh, upgraded = _fresh_and_upgraded()
    diffs = []
    for table in Base.metadata.sorted_tables:
        for name in table.columns.keys():
            f = fresh[table.name]["columns"].get(name)
            u = upgraded[table.name]["columns"].get(name)
            if (table.name, name) in _NOT_NULL_EXEMPT and f and u:
                f, u = (f[0], None, f[2], f[3]), (u[0], None, u[2], u[3])
            if f != u:
                diffs.append(f"{table.name}.{name}: fresh={f} upgraded={u}")
    assert not diffs, (
        "(type, nullable, default, pk) differ between a fresh and an upgraded install — "
        "give the model the same server_default as its ALTER:\n" + "\n".join(diffs)
    )


async def test_fresh_and_upgraded_have_the_same_indexes():
    """An index declared on a column that arrived by ALTER never reaches an
    upgraded database unless `_INDEX_DDL` builds it — `create_all` does not index
    a table that exists. Job progress ran as a full scan on every pre-2.10
    install for exactly this reason."""
    fresh, upgraded = _fresh_and_upgraded()
    diffs = []
    for table in Base.metadata.sorted_tables:
        f, u = fresh[table.name]["indexes"], upgraded[table.name]["indexes"]
        if f != u:
            diffs.append(
                f"{table.name}: only fresh={sorted(f - u)} only upgraded={sorted(u - f)}"
            )
    assert not diffs, "\n".join(diffs)


async def test_fresh_and_upgraded_agree_on_autoincrement():
    fresh, upgraded = _fresh_and_upgraded()
    diffs = [
        f"{t.name}: fresh={fresh[t.name]['autoincrement']} "
        f"upgraded={upgraded[t.name]['autoincrement']}"
        for t in Base.metadata.sorted_tables
        if fresh[t.name]["autoincrement"] != upgraded[t.name]["autoincrement"]
    ]
    assert not diffs, "\n".join(diffs)
    assert fresh["hats"]["autoincrement"], "hat ids must never be reused (tags key on them)"


async def test_a_fresh_install_boots_and_reads_every_model(tmp_path):
    """`init_db` itself, end to end, on an empty file — then a read of every
    model. The reviewer's reproduction of the AppSetting gap was exactly this."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await database.init_db(bind=engine, session_factory=factory)
        async with factory() as db:
            for model in __all_models__:
                await db.execute(select(model).limit(1))
    finally:
        await engine.dispose()


# ---- the hats AUTOINCREMENT rebuild ---------------------------------------- #


def _legacy_hats_db(engine, *, rows=(), activity_hat_ids=(), import_hat_ids=()):
    """A pre-2.81 database: every table as first shipped, hats with data."""
    with engine.begin() as conn:
        _create_legacy(conn)
        for hat_id, style in rows:
            conn.execute(
                text(
                    "INSERT INTO hats (id, condition, size, style, is_beanie, "
                    "custom_style_detail) VALUES (:id, 'new', 'standard', :style, 0, 'x')"
                ),
                {"id": hat_id, "style": style},
            )
        for hat_id in activity_hat_ids:
            conn.execute(
                text(
                    "INSERT INTO activity_log (kind, entity_type, entity_id, summary) "
                    "VALUES ('hat.deleted', 'hat', :id, 'gone')"
                ),
                {"id": hat_id},
            )
        for hat_id in import_hat_ids:
            conn.execute(
                text(
                    "INSERT INTO import_job_items (job_id, filename, status, hat_id, bytes) "
                    "VALUES (1, 'a.jpg', 'done', :id, 1)"
                ),
                {"id": hat_id},
            )


def _next_hat_id(conn) -> int:
    conn.execute(text(
        "INSERT INTO hats (condition, size, style, is_beanie) VALUES ('new', 'classic', 'a_game', 0)"
    ))
    return conn.execute(text("SELECT MAX(id) FROM hats")).scalar()


async def test_the_rebuild_keeps_every_row_and_never_reissues_a_seen_id():
    """The newest hat was deleted before the upgrade: its id (40) is only in
    the activity log now, and `MAX(hats.id)` alone would hand it straight back
    to the next hat — the sticker on the deleted hat would open that one."""
    engine = create_engine("sqlite://")
    try:
        _legacy_hats_db(
            engine, rows=[(3, "a_game"), (12, "odysea")],
            activity_hat_ids=[40], import_hat_ids=[25],
        )
        with engine.begin() as conn:
            _boot(conn)
            kept = conn.execute(text("SELECT id, style, size FROM hats ORDER BY id")).all()
            new_id = _next_hat_id(conn)
            tables = set(inspect(conn).get_table_names())
    finally:
        engine.dispose()

    assert [tuple(r) for r in kept] == [(3, "a_game", "classic"), (12, "odysea", "classic")]
    assert new_id == 41
    assert "hats_new" not in tables


async def test_after_the_rebuild_a_deleted_hats_id_is_not_reused():
    engine = create_engine("sqlite://")
    try:
        _legacy_hats_db(engine, rows=[(1, "a_game"), (2, "a_game")])
        with engine.begin() as conn:
            _boot(conn)
            conn.execute(text("DELETE FROM hats WHERE id = 2"))
            assert _next_hat_id(conn) == 3
    finally:
        engine.dispose()


async def test_an_interrupted_copy_is_discarded_and_redone():
    """Power lost after `hats_new` was created, before the swap: `hats` is
    intact and `hats_new` is a partial copy."""
    engine = create_engine("sqlite://")
    try:
        _legacy_hats_db(engine, rows=[(5, "a_game")])
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE hats_new (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
            _boot(conn)
            ids = conn.execute(text("SELECT id FROM hats")).scalars().all()
            sql = conn.execute(text(database._HATS_TABLE_SQL)).scalar()
            tables = set(inspect(conn).get_table_names())
    finally:
        engine.dispose()
    assert ids == [5]
    assert "AUTOINCREMENT" in sql
    assert "hats_new" not in tables


async def test_an_interrupted_swap_is_completed():
    """Power lost between `DROP TABLE hats` and the rename: the copy finished
    first, so `hats_new` IS the table."""
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            conn.execute(text(database._HATS_REBUILD_CREATE_DDL))
            conn.execute(text(
                "INSERT INTO hats_new (id, condition, size, style, is_beanie) "
                "VALUES (9, 'new', 'classic', 'a_game', 0)"
            ))
            _boot(conn)
            ids = conn.execute(text("SELECT id FROM hats")).scalars().all()
            tables = set(inspect(conn).get_table_names())
    finally:
        engine.dispose()
    assert ids == [9]
    assert "hats_new" not in tables


async def test_a_row_that_does_not_fit_leaves_the_table_alone_and_still_boots(caplog):
    """A NULL where the model says NOT NULL cannot be copied. The rebuild backs
    out and says so; the rest of the migration still runs."""
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            # The oldest shape, hand-written and constraint-free, so a NULL
            # can be in it at all.
            conn.execute(text(
                "CREATE TABLE hats (id INTEGER PRIMARY KEY, case_id INTEGER, "
                "position_in_case INTEGER, photo_path VARCHAR(255), condition VARCHAR(20), "
                "date_last_worn DATE, size VARCHAR(10), style VARCHAR(20), is_beanie BOOLEAN, "
                "created_at DATETIME, updated_at DATETIME)"
            ))
            conn.execute(text(
                "INSERT INTO hats (id, condition, size, style, is_beanie) "
                "VALUES (1, NULL, 'classic', 'a_game', 0)"
            ))
        with caplog.at_level(logging.ERROR, logger="headroom.database"), engine.begin() as conn:
            _boot(conn)
            sql = conn.execute(text(database._HATS_TABLE_SQL)).scalar()
            ids = conn.execute(text("SELECT id FROM hats")).scalars().all()
            tables = set(inspect(conn).get_table_names())
            indexes = {i["name"] for i in inspect(conn).get_indexes("hats")}
    finally:
        engine.dispose()
    assert "AUTOINCREMENT" not in sql
    assert ids == [1]
    assert "hats_new" not in tables
    assert "ix_hats_analysis_job_id" in indexes, "the migration carried on past the rebuild"
    assert any("Not rebuilding hats" in r.getMessage() for r in caplog.records)


async def test_the_rebuild_refuses_to_run_with_foreign_keys_enforced(caplog):
    """With enforcement on, `DROP TABLE hats` is an implicit DELETE of every
    hat, which reaches every row that references one."""
    engine = create_engine("sqlite://")
    try:
        _legacy_hats_db(engine, rows=[(1, "a_game")])
        with engine.connect() as conn:
            # Outside any transaction, where SQLite honors it.
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.commit()
            with caplog.at_level(logging.ERROR, logger="headroom.database"), conn.begin():
                _boot(conn)
                sql = conn.execute(text(database._HATS_TABLE_SQL)).scalar()
    finally:
        engine.dispose()
    assert "AUTOINCREMENT" not in sql
    assert any("foreign_keys" in r.getMessage() for r in caplog.records)


async def test_the_frozen_rebuild_ddl_agrees_with_itself():
    """The CREATE and both column lists of the copy are three hand-kept copies
    of one list; pin them to each other."""
    create = database._HATS_REBUILD_CREATE_DDL
    created = [
        part.strip().split()[0]
        for part in create[create.index("(") + 1: create.rindex(")")].split(", ")
        if not part.strip().startswith("FOREIGN KEY")
    ]
    copy = database._HATS_REBUILD_COPY_DML
    into = [c.strip() for c in copy[copy.index("(") + 1: copy.index(")")].split(",")]
    selected = [c.strip() for c in copy[copy.index("SELECT") + 6: copy.index(" FROM")].split(",")]
    assert created == into == selected


async def test_a_deleted_hats_id_is_never_handed_to_the_next_hat(client):
    """Through the API: tags are `/t/h/<id>` on stickers that cannot be
    rewritten, so the id of a deleted hat has to stay dead."""
    body = {"condition": "new", "size": "classic", "style": "a_game"}
    first = (await client.post("/api/hats", json=body)).json()["id"]
    assert (await client.delete(f"/api/hats/{first}")).status_code in (200, 204)
    second = (await client.post("/api/hats", json=body)).json()["id"]
    assert second != first
    assert (await client.get(f"/api/hats/{first}")).status_code == 404


# ---- what the schema claims ---------------------------------------------------- #


async def test_no_foreign_key_promises_a_cascade_the_engine_never_runs():
    """No `PRAGMA foreign_keys`, so an `ON DELETE CASCADE` clause is decoration:
    a color row for a hat that does not exist inserts cleanly. The cascades
    that run are the ORM's; the schema must not claim another."""
    declared = [
        f"{fk.parent.table.name}.{fk.parent.name} ON DELETE {fk.ondelete}"
        for table in Base.metadata.sorted_tables
        for fk in table.foreign_keys
        if fk.ondelete is not None
    ]
    assert declared == []


async def test_the_app_engine_does_not_enforce_foreign_keys(tmp_path):
    """The premise of the test above, and of the hats rebuild (a DROP under
    enforcement would reach every referencing row). If this ever flips, both
    need revisiting — this is the test that says so."""
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fk.db'}")
    event.listen(engine.sync_engine, "connect", database._sqlite_pragmas)
    try:
        async with engine.connect() as conn:
            assert (await conn.exec_driver_sql("PRAGMA foreign_keys")).scalar() == 0
    finally:
        await engine.dispose()


async def test_each_price_clump_is_one_set_of_names_from_model_to_wire():
    """The clumps travel together (`models.hat` mixins), and each is declared
    ONCE on the wire too: one pydantic base per mixin, name for name, which
    `HatRead` inherits rather than restating, and which the admin eBay
    refresh echoes as-is."""
    from headroom.models.hat import (
        DispositionColumns,
        EbayCompsColumns,
        NewPriceColumns,
        ResaleColumns,
    )
    from headroom.routes.admin import ebay as ebay_routes
    from headroom.schemas.hat import (
        DispositionFields,
        EbayComps,
        HatRead,
        NewPriceFields,
        ResaleFields,
    )

    hat_columns = {c.name for c in Base.metadata.tables["hats"].columns}
    for mixin, base in (
        (NewPriceColumns, NewPriceFields),
        (ResaleColumns, ResaleFields),
        (EbayCompsColumns, EbayComps),
        (DispositionColumns, DispositionFields),
    ):
        names = set(mixin.__annotations__)
        assert names <= hat_columns, (mixin.__name__, names - hat_columns)
        assert set(base.model_fields) == names, (base.__name__, set(base.model_fields) ^ names)
        assert issubclass(HatRead, base), f"HatRead restates {base.__name__} instead of inheriting it"
    assert ebay_routes.EbayComps is EbayComps


# ---- data migrations that ride along ---------------------------------------- #


async def test_the_import_status_rename_migrates_stored_rows():
    """`cancelled` → `canceled` is a rename of a PERSISTED value, so an upgraded
    database must come out speaking the new spelling everywhere the old one was
    stored: both status columns and the activity kind. Idempotent — running the
    migration twice changes nothing more."""
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
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


async def test_cases_from_before_rooms_land_in_the_default_room(tmp_path):
    """`room_id` used to be added `DEFAULT 1` — the hardcoded room the flag
    replaced. It is added empty now, and `init_db` files every case that has
    no room into whichever room holds the flag."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'old.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, case_type VARCHAR(12), "
                "sequence_number INTEGER, display_id VARCHAR(10), photo_path VARCHAR(255), "
                "created_at DATETIME, updated_at DATETIME)"
            ))
            await conn.execute(text(
                "INSERT INTO cases (case_type, sequence_number, display_id) VALUES ('archive', 1, 'A-001')"
            ))
        await database.init_db(bind=engine, session_factory=factory)
        async with engine.connect() as conn:
            room_id = (await conn.execute(text("SELECT room_id FROM cases"))).scalar()
            default = (await conn.execute(text("SELECT id FROM rooms WHERE is_default = 1"))).scalar()
            dflt = [
                c["default"] for c in await conn.run_sync(
                    lambda sync: inspect(sync).get_columns("cases")
                ) if c["name"] == "room_id"
            ]
    finally:
        await engine.dispose()
    assert room_id == default is not None
    assert dflt == [None], "no hardcoded room left in the schema"
