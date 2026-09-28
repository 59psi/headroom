"""Where a backup stages its bytes, and what each kind of archive carries.

Staging: the shipped compose file runs the app with a read-only root and
`tmpfs: - /tmp`, and a tmpfs is RAM charged to the container's 1 GB memory
limit. `stream_backup` spooled the whole on-demand archive into
`tempfile.gettempdir()` — the one directory that, under that compose file, is
memory — so the documented pre-upgrade download could OOM-kill the app. The
`VACUUM INTO` snapshot went the same way. Both now stage on the data volume.

Scope: the Settings card has always said "Database only = just headroom.db",
and the database-only archive also carried Caddy's root and intermediate
PRIVATE KEYS, because the CA was added whatever the flag said.
"""

from __future__ import annotations

import asyncio
import contextlib
import tarfile
import tempfile
from pathlib import Path

import pytest

from headroom.config import settings
from headroom.services import backup_service, ca_vault

pytestmark = pytest.mark.anyio


def _seed_db(tmp_path, monkeypatch) -> Path:
    import sqlite3

    db = tmp_path / "headroom.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE hats (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO hats (name) VALUES ('one')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(backup_service, "_db_path", lambda: db)
    (settings.upload_dir / "hats" / "one.png").write_bytes(b"png")
    return db


def _seed_ca(tmp_path, monkeypatch) -> None:
    pki = tmp_path / "caddy-ca" / "pki"
    pki.mkdir(parents=True)
    for name in ca_vault.PKI_FILES:
        (pki / name).write_text(f"-----BEGIN {name}-----\n")
    monkeypatch.setattr(ca_vault, "PKI_DIR", pki)
    monkeypatch.setenv("HEADROOM_BACKUP_INCLUDE_CA", "true")


def _spool_root() -> Path:
    return backup_service._backup_dir() / backup_service.SPOOL_DIR_NAME


@pytest.fixture
def ram_tmp(tmp_path, monkeypatch):
    """Stand-in for the container's /tmp tmpfs: anything written here is RAM."""
    ram = tmp_path / "tmpfs"
    ram.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(ram))
    return ram


# ---- staging lives on the data volume ----------------------------------- #


async def test_the_on_demand_archive_is_spooled_on_the_data_volume_not_in_tmp(
    tmp_path, monkeypatch, ram_tmp
):
    _seed_db(tmp_path, monkeypatch)

    gen = backup_service.stream_backup(include_uploads=True)
    first = await gen.__anext__()
    try:
        assert first[:2] == b"\x1f\x8b"
        # Mid-download: the whole archive is sitting somewhere. It must be on
        # the volume, and nothing may have gone into the tmpfs stand-in.
        assert list(ram_tmp.iterdir()) == [], (
            "the archive was staged in the temp dir — a RAM tmpfs under the "
            "shipped compose file, charged to the container's memory limit"
        )
        staged = list(_spool_root().glob("headroom-stream-*/backup.tar.gz"))
        assert len(staged) == 1, "the archive is not staged under backups/.spool"
    finally:
        await gen.aclose()

    assert list(_spool_root().iterdir()) == [], "the staged archive outlived the download"


async def test_the_database_snapshot_is_staged_on_the_data_volume(
    tmp_path, monkeypatch, ram_tmp
):
    """`VACUUM INTO` writes a whole copy of the database. Same rule."""
    _seed_db(tmp_path, monkeypatch)
    seen: dict = {}
    real = backup_service._snapshot_db_sync

    def _spy(db, dest_dir):
        seen["dest_dir"] = Path(dest_dir)
        return real(db, dest_dir)

    monkeypatch.setattr(backup_service, "_snapshot_db_sync", _spy)

    backup_service._build_tarball_sync(tmp_path / "out.tar.gz")

    assert seen["dest_dir"].is_relative_to(_spool_root()), (
        f"the snapshot was staged at {seen['dest_dir']}, off the data volume"
    )
    assert list(ram_tmp.iterdir()) == []
    assert not seen["dest_dir"].exists(), "the snapshot staging was not cleaned up"


async def test_staging_a_dead_process_left_behind_is_reclaimed(tmp_path, monkeypatch):
    """A volume, unlike a tmpfs, does not empty itself on restart.

    A SIGKILL mid-download runs no `finally`, so the staged archive stays on
    the card. Anything under `.spool/` that no live download or backup claims
    belongs to a dead process — and must go the next time anything is staged,
    without touching a staging directory that IS in use.
    """
    _seed_db(tmp_path, monkeypatch)
    dead = _spool_root() / "headroom-stream-deadbeef"
    dead.mkdir(parents=True)
    (dead / "backup.tar.gz").write_bytes(b"x" * 1024)

    live = backup_service._open_spool_sync("headroom-stream-")
    try:
        assert not dead.exists(), "a dead process's staged archive survived"
        assert live.exists()

        # A second, concurrent staging must not sweep the first one away.
        other = backup_service._open_spool_sync("headroom-snap-")
        assert live.exists(), "one live staging directory swept another"
        backup_service._close_spool_sync(other)
    finally:
        backup_service._close_spool_sync(live)
    assert not live.exists()


@pytest.fixture
def _scheduler_health():
    """The scheduler writes the process-global health record; give it back."""
    saved = backup_service._health
    backup_service._health = backup_service.BackupHealth()
    yield
    backup_service._health = saved


async def _run_scheduler_until(done, *, timeout: float = 2.0) -> None:
    """Start the real scheduler, wait (real time — its sweeps are on worker
    threads) until `done()` holds or `timeout` passes, then cancel it."""
    task = asyncio.create_task(backup_service.scheduled_backup_loop(24.0, 5))
    deadline = asyncio.get_running_loop().time() + timeout
    while not done() and not task.done() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_the_scheduler_reclaims_dead_staging_at_boot(monkeypatch, _scheduler_health):
    """The scheduler itself, started the way the lifespan starts it: at boot
    nothing is in flight, so everything under `.spool/` is a dead process's.
    (This used to call the sweep function directly, which passed just as well
    with the scheduler never calling it.)"""
    dead = _spool_root() / "headroom-snap-deadbeef"
    dead.mkdir(parents=True)
    (dead / "headroom.db").write_bytes(b"x" * 1024)
    # A recent backup exists, so the first pass writes nothing — the sweep is
    # the only thing that can remove the directory.
    monkeypatch.setattr(backup_service, "_seconds_since_newest_backup_sync", lambda: 60.0)

    await _run_scheduler_until(lambda: not dead.exists())

    assert not dead.exists(), "the scheduler started without reclaiming dead staging"


async def test_a_data_volume_it_cannot_reach_at_boot_does_not_kill_the_scheduler(
    monkeypatch, _scheduler_health
):
    """The boot sweeps run BEFORE the loop's per-pass try. The staging sweep
    creates `backups/.spool/` first, and on a read-only or not-yet-mounted
    `/data` that raised straight out of the task — the scheduler dead for the
    life of the process, the exact failure `scheduled_backup_loop` exists to
    survive. A sweep is housekeeping; it costs the sweep, never the task."""
    def _unreachable():
        raise PermissionError("/data not writable")

    attempts = 0

    async def _count(keep, fingerprint=None):
        nonlocal attempts
        attempts += 1

    monkeypatch.setattr(backup_service, "_backup_dir", _unreachable)
    monkeypatch.setattr(backup_service, "_seconds_since_newest_backup_sync", lambda: None)
    monkeypatch.setattr(backup_service, "_data_fingerprint_sync", lambda: "changed")
    monkeypatch.setattr(backup_service, "_read_fingerprint_sync", lambda: None)
    monkeypatch.setattr(backup_service, "write_scheduled_backup", _count)

    await _run_scheduler_until(lambda: attempts > 0)

    assert attempts > 0, "an unreachable volume at boot killed the scheduler before its first pass"


async def test_the_staged_archive_is_deleted_off_the_event_loop(tmp_path, monkeypatch):
    """Deleting a multi-hundred-megabyte archive from an SD card is not instant.

    The generator's `finally` ran `shutil.rmtree` directly — on the loop, in
    the one module whose own comments say a 1 MB read there stalls every other
    request. It now runs in a worker thread.
    """
    import threading

    _seed_db(tmp_path, monkeypatch)
    loop_thread = threading.get_ident()
    calls: list[int] = []
    real_rmtree = backup_service.shutil.rmtree

    def _spy(path, *args, **kwargs):
        calls.append(threading.get_ident())
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(backup_service.shutil, "rmtree", _spy)

    async for _ in backup_service.stream_backup(include_uploads=False):
        pass

    assert calls, "the staged archive was never deleted"
    assert loop_thread not in calls, "the staged archive was deleted on the event loop"


async def test_staging_is_invisible_to_the_backup_inventory(tmp_path, monkeypatch):
    """`.spool/` sits beside the archives; it must never read as one."""
    _seed_db(tmp_path, monkeypatch)
    live = backup_service._open_spool_sync("headroom-stream-")
    try:
        (live / "backup.tar.gz").write_bytes(b"\x1f\x8b")
        assert backup_service._list_backups_sync() == []
        assert backup_service._sweep_partials_sync() == 0
    finally:
        backup_service._close_spool_sync(live)


# ---- what each archive carries ------------------------------------------ #


def _members(path: Path) -> list[str]:
    with tarfile.open(path, "r:gz") as tar:
        return tar.getnames()


async def test_a_database_only_archive_is_the_database_alone(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)
    _seed_ca(tmp_path, monkeypatch)

    out = tmp_path / "db-only.tar.gz"
    backup_service._build_tarball_sync(out, False)

    names = _members(out)
    assert "data/headroom.db" in names
    assert not any(n.startswith("data/caddy-pki") for n in names), (
        f"a 'database only' archive carried the CA's private keys: {names}"
    )
    assert not any(n.startswith("data/uploads") for n in names)


async def test_the_database_only_download_carries_no_ca(tmp_path, monkeypatch):
    """The same property at the endpoint's entry point, `stream_backup`."""
    _seed_db(tmp_path, monkeypatch)
    _seed_ca(tmp_path, monkeypatch)

    body = b"".join([c async for c in backup_service.stream_backup(include_uploads=False)])
    out = tmp_path / "download.tar.gz"
    out.write_bytes(body)

    assert not any(n.startswith("data/caddy-pki") for n in _members(out))


async def test_a_full_archive_still_carries_the_ca(tmp_path, monkeypatch):
    """The other direction, so "never include it" cannot pass as the fix."""
    _seed_db(tmp_path, monkeypatch)
    _seed_ca(tmp_path, monkeypatch)

    out = tmp_path / "full.tar.gz"
    backup_service._build_tarball_sync(out)

    names = _members(out)
    assert "data/caddy-pki/root.key" in names
    assert "data/uploads/hats/one.png" in names
