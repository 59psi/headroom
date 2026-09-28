"""Backups must capture data that is still sitting in the WAL.

The DB runs in WAL mode (`database.py`), so a commit lives in `headroom.db-wal`
until a checkpoint folds it into the main file. Tarring only `headroom.db`
therefore silently drops everything committed since the last checkpoint — and
a checkpoint landing mid-read can also produce a torn copy. Both failures are
invisible until a restore, which is the worst possible time to discover them.
"""

from __future__ import annotations

import asyncio
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


@pytest.mark.anyio
async def test_backup_download_streams_in_chunks(client, tmp_path, monkeypatch):
    """Memory must not scale with collection size.

    The generator used to build the whole tarball into a BytesIO and yield it
    as ONE chunk — the entire database plus every photo resident at once, on
    the same Pi that holds a 179MB rembg model. Now that the container has a
    memory limit, the one operation whose job is protecting the data was the
    one most able to kill the process.
    """
    # Force several chunks out of a small payload rather than fabricating a
    # multi-megabyte fixture. The payload has to be INCOMPRESSIBLE, though: an
    # empty test database gzips to under 512 bytes, so the old `>= 1` assertion
    # was satisfied by a single chunk and never showed streaming at all.
    import os

    from headroom.config import settings
    from headroom.services import backup_service

    (settings.upload_dir / "hats").mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / "hats" / "noise.bin").write_bytes(os.urandom(4096))
    monkeypatch.setattr(backup_service, "_STREAM_CHUNK", 512)

    chunks = [c async for c in backup_service.stream_backup(include_uploads=True)]

    assert len(chunks) > 1, "a test named 'streams in chunks' must see more than one"
    assert all(len(c) <= 512 for c in chunks), "a chunk exceeded the read size"
    # Still a valid gzip stream once reassembled.
    assert b"".join(chunks)[:2] == b"\x1f\x8b"


@pytest.mark.anyio
async def test_streaming_cleans_up_its_temp_copy(client, monkeypatch):
    """A finished download must not leave a full copy of the collection behind.

    Looks where the archive is actually staged — `backups/.spool/` on the data
    volume (see `test_backup_staging.py`). This used to glob the system temp
    dir, and would have gone on passing there, vacuously, after the spool
    moved.
    """
    from headroom.services import backup_service

    spool = backup_service._backup_dir() / backup_service.SPOOL_DIR_NAME
    async for _ in backup_service.stream_backup(include_uploads=False):
        assert list(spool.glob("headroom-stream-*")), "not staged where this test looks"
    assert list(spool.glob("headroom-stream-*")) == [], "the staged tarball was left behind"


@pytest.mark.anyio
async def test_an_abandoned_download_cleans_up_too(client, tmp_path, monkeypatch):
    """An abandoned download must not leak a full copy of the collection.

    A client that disconnects mid-download closes the generator EARLY, which
    is a different exit from the finished download above: cleanup that ran
    only on normal completion passed a test that read the stream to its end.
    So this takes one chunk of several and closes.

    It also used to glob the system temp dir, shared with every other process
    on the machine, and failed on another run's leftovers. Staging is on the
    data volume now; the temp dir is pointed at a private directory anyway so
    that nothing here can read — or be failed by — shared state.
    """
    import os
    import tempfile

    from headroom.config import settings
    from headroom.services import backup_service

    private_tmp = tmp_path / "system-tmp"
    private_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(private_tmp))
    (settings.upload_dir / "hats" / "noise.bin").write_bytes(os.urandom(4096))
    monkeypatch.setattr(backup_service, "_STREAM_CHUNK", 512)
    spool = backup_service._backup_dir() / backup_service.SPOOL_DIR_NAME

    gen = backup_service.stream_backup(include_uploads=True)
    await gen.__anext__()
    staged = list(spool.glob("headroom-stream-*"))
    # Preconditions: the archive is staged where this test looks, and the
    # download really is being cut off partway (more than one chunk is left).
    assert len(staged) == 1, "not staged where this test looks"
    assert (staged[0] / "backup.tar.gz").stat().st_size > 2 * 512, "one chunk was the whole archive"
    await gen.aclose()

    assert not staged[0].exists(), "an abandoned download leaked its archive"
    assert list(spool.iterdir()) == [], "an abandoned download left staging behind"
    assert list(private_tmp.iterdir()) == [], "the download staged in the system temp dir"


@pytest.mark.anyio
async def test_a_degraded_backup_says_so_inside_the_archive(client, monkeypatch, tmp_path):
    """A torn fallback backup must not look identical to a clean snapshot.

    The fallback copies the DB while writers may be mid-transaction, so it can
    restore as "database disk image is malformed" — and the only moment you'd
    find out was the restore itself.
    """
    import tarfile

    from headroom.services import backup_service

    # Its own database file. This test used to find one at `_db_path()`
    # anyway — the empty `./headroom.db` that a bare `checkpoint_wal()` in
    # `test_durability` created in the working directory on every run. It
    # passed because another test polluted the checkout, and it would have
    # failed the moment that test was fixed or run in a different order.
    db = tmp_path / "headroom.db"
    db.write_bytes(b"not really sqlite, and that is fine: the copy is what fails")
    monkeypatch.setattr(backup_service, "_db_path", lambda: db)

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
