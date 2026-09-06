"""A backup archive exists under its real name only once it is whole.

Measured before the fix, on a volume holding 600 MB of photos: `docker stop`
four seconds into the first scheduled backup returned in 0 s (the tar thread
is abandoned on cancellation) and left a 161 MB `headroom-backup-….tar.gz`
that `gzip -t` rejected. Everything downstream trusted the name — `GET
/api/admin/backups` listed it, the health record called it the last success,
the boot backup was skipped because "a recent one exists", and retention
KEPT it while deleting the real one. The 200-byte upload marker beside it
already got tmp+rename; the artifact that matters did not.
"""

from __future__ import annotations

import os
import tarfile
import time

import pytest

from headroom.config import settings
from headroom.services import backup_service

pytestmark = pytest.mark.anyio


def _seed(tmp_path, monkeypatch):
    db = tmp_path / "headroom.db"
    db.write_bytes(b"not really sqlite but bytes are bytes")
    monkeypatch.setattr(backup_service, "_db_path", lambda: db)
    (settings.upload_dir / "hats").mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / "hats" / "one.png").write_bytes(b"png")
    backup_service._backup_dir().mkdir(parents=True, exist_ok=True)


async def test_a_crash_mid_write_leaves_no_archive_under_a_real_name(
    isolated_upload_dir, tmp_path, monkeypatch
):
    _seed(tmp_path, monkeypatch)

    class PowerCut(BaseException):
        pass

    def _dies_mid_tar(tar, db, tmp):
        raise PowerCut()

    monkeypatch.setattr(backup_service, "_add_db_to_tar", _dies_mid_tar)
    target = backup_service._backup_dir() / backup_service._timestamped_name()

    with pytest.raises(PowerCut):
        backup_service._build_tarball_sync(target)

    assert not target.exists(), "a torn archive under the real name"
    assert not backup_service.partial_path(target).exists(), "the partial is cleaned up on failure"
    assert backup_service._list_backups_sync() == []
    assert backup_service._seconds_since_newest_backup_sync() is None


async def test_a_partial_left_by_a_dead_process_is_invisible_and_swept(
    isolated_upload_dir, tmp_path, monkeypatch
):
    """A SIGKILL cannot run the cleanup above; the partial stays on disk
    under its `.partial` name. Nothing may read it as a backup, and the next
    boot removes it."""
    _seed(tmp_path, monkeypatch)
    real = backup_service._backup_dir() / "headroom-backup-2026-09-01T00-00-00Z.tar.gz"
    backup_service._build_tarball_sync(real)
    torn = backup_service.partial_path(
        backup_service._backup_dir() / "headroom-backup-2026-09-06T00-00-00Z.tar.gz"
    )
    torn.write_bytes(b"\x1f\x8b" + b"x" * 100)
    # The whole archive is an hour old; the torn one is fresh.
    an_hour_ago = time.time() - 3600
    os.utime(real, (an_hour_ago, an_hour_ago))

    assert backup_service._list_backups_sync() == [real]
    age = backup_service._seconds_since_newest_backup_sync()
    assert age is not None and age > 3500, "the fresh torn file must not count as the newest backup"
    backup_service._enforce_retention(1)
    assert real.exists(), "retention kept the whole archive, not the torn one"

    assert backup_service._sweep_partials_sync() == 1
    assert not torn.exists()
    assert real.exists()


async def test_a_finished_archive_is_whole_and_under_its_final_name(
    isolated_upload_dir, tmp_path, monkeypatch
):
    _seed(tmp_path, monkeypatch)
    target = backup_service._backup_dir() / backup_service._timestamped_name()

    backup_service._build_tarball_sync(target)

    assert target.exists()
    assert not backup_service.partial_path(target).exists()
    with tarfile.open(target, "r:gz") as tar:
        names = tar.getnames()
    assert "data/headroom.db" in names
    assert "data/uploads/hats/one.png" in names
