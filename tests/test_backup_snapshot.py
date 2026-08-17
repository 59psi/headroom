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

import asyncio

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


@pytest.mark.anyio
async def test_backup_download_streams_in_chunks(client, tmp_path, monkeypatch):
    """Memory must not scale with collection size.

    The generator used to build the whole tarball into a BytesIO and yield it
    as ONE chunk — the entire database plus every photo resident at once, on
    the same Pi that holds a 179MB rembg model. Now that the container has a
    memory limit, the one operation whose job is protecting the data was the
    one most able to kill the process.
    """
    from headroom.services import backup_service

    # Force several chunks out of a small payload rather than fabricating a
    # multi-megabyte fixture.
    monkeypatch.setattr(backup_service, "_STREAM_CHUNK", 512)

    chunks = [c async for c in backup_service.stream_backup(include_uploads=True)]

    assert len(chunks) >= 1
    assert all(len(c) <= 512 for c in chunks), "a chunk exceeded the read size"
    # Still a valid gzip stream once reassembled.
    assert b"".join(chunks)[:2] == b"\x1f\x8b"


@pytest.mark.anyio
async def test_streaming_cleans_up_its_temp_copy(client, monkeypatch):
    """An abandoned download must not leak a full copy of the collection."""
    import tempfile
    from pathlib import Path

    from headroom.services import backup_service

    before = {p.name for p in Path(tempfile.gettempdir()).glob("headroom-stream-*")}
    async for _ in backup_service.stream_backup(include_uploads=False):
        pass
    after = {p.name for p in Path(tempfile.gettempdir()).glob("headroom-stream-*")}

    assert after == before, "the temp tarball was left behind"


@pytest.mark.anyio
async def test_a_degraded_backup_says_so_inside_the_archive(client, monkeypatch, tmp_path):
    """A torn fallback backup must not look identical to a clean snapshot.

    The fallback copies the DB while writers may be mid-transaction, so it can
    restore as "database disk image is malformed" — and the only moment you'd
    find out was the restore itself.
    """
    import tarfile

    from headroom.services import backup_service

    def _fail(db, dest_dir):
        raise RuntimeError("VACUUM INTO unavailable")

    monkeypatch.setattr(backup_service, "_snapshot_db_sync", _fail)

    out = tmp_path / "b.tar.gz"
    await asyncio.to_thread(backup_service._build_tarball_sync, out, False)

    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
        assert "data/DEGRADED-BACKUP-README.txt" in names
        body = tar.extractfile("data/DEGRADED-BACKUP-README.txt").read().decode()
    assert "VACUUM INTO unavailable" in body
    assert "integrity_check" in body
