"""The pre-upgrade snapshot: when it is taken, what it holds, how many stay.

The boot wiring (it runs before `init_db`, the version is recorded last, a
failed snapshot does not stop the boot) is in `test_lifespan_wiring.py`,
which boots the real lifespan. These pin the guard's own decisions.
"""

import os
import sqlite3

import pytest
from sqlalchemy.engine import make_url

from headroom.services import upgrade_guard

pytestmark = pytest.mark.anyio


def _make_db(path, *, version=None, settings_table=True):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE hats (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO hats (name) VALUES ('odysea')")
    if settings_table:
        conn.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT)")
        if version is not None:
            conn.execute(
                "INSERT INTO app_settings VALUES (?, ?)", (upgrade_guard.LAST_BOOTED_KEY, version)
            )
    conn.commit()
    return conn


def _names(snapshot):
    conn = sqlite3.connect(snapshot)
    try:
        return [r[0] for r in conn.execute("SELECT name FROM hats ORDER BY id")]
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("sqlite+aiosqlite:////data/headroom.db", "/data/headroom.db"),
        ("sqlite+aiosqlite:///:memory:", None),
        ("sqlite+aiosqlite://", None),
        ("postgresql+asyncpg://u@h/db", None),
    ],
)
async def test_the_database_file_is_read_from_the_engine_url(url, expected):
    got = upgrade_guard.sqlite_file(make_url(url))
    assert (str(got) if got else None) == expected


async def test_a_relative_url_resolves_against_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    got = upgrade_guard.sqlite_file(make_url("sqlite+aiosqlite:///./headroom.db"))
    assert got == tmp_path / "./headroom.db"


async def test_nothing_to_protect_on_a_fresh_install(tmp_path):
    dest = tmp_path / "backups"
    assert upgrade_guard.snapshot_before_upgrade(None, dest, "2.81.1") is None
    assert upgrade_guard.snapshot_before_upgrade(tmp_path / "absent.db", dest, "2.81.1") is None
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    assert upgrade_guard.snapshot_before_upgrade(empty, dest, "2.81.1") is None
    assert not dest.exists()


async def test_the_same_version_as_last_boot_takes_no_snapshot(tmp_path):
    db = tmp_path / "headroom.db"
    _make_db(db, version="2.81.1").close()
    assert upgrade_guard.snapshot_before_upgrade(db, tmp_path / "b", "2.81.1") is None


async def test_a_new_version_gets_a_copy_of_the_database_as_it_was(tmp_path):
    db = tmp_path / "headroom.db"
    _make_db(db, version="2.81.0").close()
    snap = upgrade_guard.snapshot_before_upgrade(db, tmp_path / "backups", "2.81.1")
    assert snap is not None and snap.exists()
    assert snap.name.startswith("pre-upgrade-2.81.0-to-2.81.1-")
    assert snap.suffix == ".db"
    assert _names(snap) == ["odysea"]
    assert not list((tmp_path / "backups").glob("*.partial"))


async def test_a_transaction_still_in_the_wal_is_in_the_snapshot(tmp_path):
    """After an unclean stop the newest commits live only in `-wal`. A copy of
    the main file alone — or a read-only open that cannot replay the WAL —
    would be a backup of the database before its latest changes."""
    db = tmp_path / "headroom.db"
    writer = _make_db(db, version="2.81.0")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("INSERT INTO hats (name) VALUES ('trenches')")
    writer.commit()
    assert os.path.getsize(f"{db}-wal") > 0  # the row is in the WAL, not the file
    try:
        snap = upgrade_guard.snapshot_before_upgrade(db, tmp_path / "backups", "2.81.1")
    finally:
        writer.close()
    assert _names(snap) == ["odysea", "trenches"]


async def test_a_database_from_before_the_settings_table_is_snapshotted(tmp_path):
    db = tmp_path / "headroom.db"
    _make_db(db, settings_table=False).close()
    assert upgrade_guard.last_booted(db) is None
    snap = upgrade_guard.snapshot_before_upgrade(db, tmp_path / "backups", "2.81.1")
    assert snap.name.startswith("pre-upgrade-unknown-to-2.81.1-")


async def test_only_the_newest_three_snapshots_are_kept(tmp_path):
    dest = tmp_path / "backups"
    dest.mkdir()
    for i in range(5):
        p = dest / f"pre-upgrade-2.7{i}.0-to-2.7{i + 1}.0-x.db"
        p.write_bytes(b"x")
        os.utime(p, (1_000 + i, 1_000 + i))
    (dest / "pre-upgrade-a-to-b-x.db.partial").write_bytes(b"torn")
    # A scheduled archive in the same directory is not the guard's to prune.
    archive = dest / "headroom-backup-2026-09-27T22-53-45Z.tar.gz"
    archive.write_bytes(b"x")

    upgrade_guard.prune(dest)

    kept = sorted(p.name for p in dest.glob("pre-upgrade-*"))
    assert kept == [
        "pre-upgrade-2.72.0-to-2.73.0-x.db",
        "pre-upgrade-2.73.0-to-2.74.0-x.db",
        "pre-upgrade-2.74.0-to-2.75.0-x.db",
    ]
    assert archive.exists()
