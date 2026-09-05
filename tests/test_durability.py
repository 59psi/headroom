"""Committed means committed, even if the power goes out.

Written after an unclean shutdown on the real deployment destroyed Caddy's
stored private key and a lock file — written, never fsynced, gone — which broke
HTTPS for 37 days. The database sits on the same SD card under the same power,
and it was running `PRAGMA synchronous=NORMAL`.

`NORMAL` is SQLite's own recommendation for WAL mode and it is safe from
CORRUPTION, which is what most guidance means by "safe". It is not safe from
LOSS: SQLite's documentation says a transaction committed under `NORMAL` "might
roll back following a power loss", because the WAL is synced at a checkpoint
rather than at commit. The default checkpoint threshold is 1000 pages, so what
is at risk is not the last write — it is every write since the last checkpoint.

These tests pin the setting itself rather than any behavior above it, because
nothing in the app can observe its own durability. A regression here is
invisible until the one moment it matters.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from headroom import database

from tests.conftest import test_engine as engine_under_test

pytestmark = pytest.mark.anyio

#: `PRAGMA synchronous` answers with an integer, not the keyword.
_SYNCHRONOUS_VALUES = {0: "OFF", 1: "NORMAL", 2: "FULL", 3: "EXTRA"}


async def test_the_default_is_durable():
    """The whole point. `FULL` fsyncs the WAL on every commit."""
    assert database.DEFAULT_SYNCHRONOUS == "FULL"
    assert database.sqlite_synchronous() == "FULL"


async def test_a_connection_actually_gets_it(db_session):
    """Not just what the resolver returns — what the connection is running.

    The resolver could be perfect while the pragma never reaches SQLite (a
    typo in the PRAGMA text, a hook that stopped firing). This asks the
    database what mode it is in.
    """
    raw = (await db_session.execute(text("PRAGMA synchronous"))).scalar()

    assert _SYNCHRONOUS_VALUES.get(raw) in ("FULL", "EXTRA"), (
        f"connection is running synchronous={_SYNCHRONOUS_VALUES.get(raw, raw)} — "
        "commits are not fsynced and a power cut loses them"
    )


async def test_wal_is_still_the_journal_mode(db_session):
    """FULL must not have been achieved by giving up WAL.

    Rollback-journal mode would also be durable and would serialize readers
    against writers, which is what WAL is here to avoid on a Pi.
    """
    mode = (await db_session.execute(text("PRAGMA journal_mode"))).scalar()

    assert str(mode).lower() in ("wal", "memory"), mode


@pytest.mark.parametrize("raw,expected", [
    ("FULL", "FULL"),
    ("full", "FULL"),
    ("  Extra  ", "EXTRA"),
    ("NORMAL", "NORMAL"),
    ("OFF", "OFF"),
])
async def test_a_recognized_override_is_honored(monkeypatch, raw, expected):
    """Someone whose hardware makes the trade differently can make it."""
    monkeypatch.setenv("HEADROOM_SQLITE_SYNCHRONOUS", raw)

    assert database.sqlite_synchronous() == expected


@pytest.mark.parametrize("bad", ["", "FUL", "yes", "1", "TRUE", "; DROP TABLE hats"])
async def test_an_unrecognized_value_falls_back_to_durable(monkeypatch, bad):
    """A typo must not silently turn durability off.

    This is also the injection guard: the value is interpolated into a PRAGMA,
    which cannot take a bound parameter, so anything outside the whitelist has
    to be discarded rather than passed through.
    """
    monkeypatch.setenv("HEADROOM_SQLITE_SYNCHRONOUS", bad)

    assert database.sqlite_synchronous() == "FULL"


async def test_the_whitelist_is_the_only_thing_that_can_reach_the_pragma():
    """Pins the closed set, since it is spliced into SQL."""
    assert set(database.SYNCHRONOUS_MODES) == {"FULL", "EXTRA", "NORMAL", "OFF"}
    for mode in database.SYNCHRONOUS_MODES:
        assert mode.isalpha(), mode


# ---- the shutdown checkpoint ------------------------------------------- #


async def test_checkpointing_the_wal_does_not_raise():
    """Runs on the shutdown path, so it must never turn a stop into a crash.

    On `test_engine`, explicitly. The bare call used the module engine, which
    pointed at `./headroom.db` — and this test created that file in the
    working directory and touched its WAL sidecars on every run. Empty, so
    nobody noticed; `conftest` now points the module engine at an unopenable
    path so the same slip fails instead of leaving artifacts.
    """
    await database.checkpoint_wal(engine_under_test)


async def test_a_failing_checkpoint_is_swallowed(caplog):
    """A broken checkpoint must not abort the rest of shutdown.

    The lifespan already learned this the hard way with background tasks: one
    raising step used to skip every step after it.
    """
    class _Boom:
        def begin(self):
            raise RuntimeError("disk gone")

        dialect = engine_under_test.dialect

    caplog.set_level("WARNING")

    await database.checkpoint_wal(_Boom())

    assert any("checkpoint" in r.getMessage().lower() for r in caplog.records)
