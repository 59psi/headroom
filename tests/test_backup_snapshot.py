"""Backups must capture data that is still sitting in the WAL.

The DB runs in WAL mode (`database.py`), so a commit lives in `headroom.db-wal`
until a checkpoint folds it into the main file. Tarring only `headroom.db`
therefore silently drops everything committed since the last checkpoint — and
a checkpoint landing mid-read can also produce a torn copy. Both failures are
invisible until a restore, which is the worst possible time to discover them.
"""

from __future__ import annotations

import sqlite3
import tarfile
from pathlib import Path

import pytest

from headroom.services import backup_service

pytestmark = pytest.mark.anyio


def _wal_db_with_uncheckpointed_row(tmp_path: Path) -> Path:
    """A WAL database whose newest row is NOT yet in the main file."""
    db = tmp_path / "headroom.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE hats (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO hats (name) VALUES ('only-in-the-wal')")
    conn.commit()
    # Deliberately left open: closing checkpoints and removes the WAL, which
    # would hide exactly the bug under test.
    assert (tmp_path / "headroom.db-wal").exists(), "test needs a live WAL"
    return db


async def test_snapshot_captures_rows_still_in_the_wal(tmp_path):
    db = _wal_db_with_uncheckpointed_row(tmp_path)

    dest_dir = tmp_path / "snap"
    dest_dir.mkdir()
    snapshot = backup_service._snapshot_db_sync(db, dest_dir)

    rows = sqlite3.connect(snapshot).execute("SELECT name FROM hats").fetchall()
    assert rows == [("only-in-the-wal",)], (
        "the snapshot lost a committed row — it copied the main DB file and "
        "ignored the write-ahead log"
    )
    assert not (dest_dir / "headroom.db-wal").exists(), (
        "the snapshot must be self-contained, with no sidecar to restore beside it"
    )


async def test_tar_falls_back_to_the_raw_file_set_when_snapshotting_fails(
    tmp_path, monkeypatch
):
    """A broken snapshot must still yield a restorable-with-effort backup.

    Losing the backup entirely because the snapshot failed would be a worse
    outcome than shipping the raw file set, so the WAL sidecars go in instead.
    """
    db = _wal_db_with_uncheckpointed_row(tmp_path)

    def _boom(*_a, **_k):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(backup_service, "_snapshot_db_sync", _boom)

    out = tmp_path / "backup.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        backup_service._add_db_to_tar(tar, db, tmp_path / "unused")

    names = tarfile.open(out).getnames()
    assert "data/headroom.db" in names
    assert "data/headroom.db-wal" in names, (
        "without the WAL the fallback would ship the same lossy backup the "
        "snapshot exists to prevent"
    )
