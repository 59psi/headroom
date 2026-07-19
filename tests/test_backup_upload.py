"""Off-site backup upload hook (HEADROOM_BACKUP_UPLOAD_CMD).

The hook shells out to an operator-provided uploader (rclone, scp, aws…) after
each scheduled backup. These tests drive it with ordinary POSIX commands (cp,
false) so no network or external tool is involved.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from headroom.services import backup_service

pytestmark = pytest.mark.anyio


def _fake_backup(tmp_path: Path) -> Path:
    # Own subdir so assertions aren't polluted by the autouse uploads fixture,
    # which also lives under tmp_path.
    d = tmp_path / "bk"
    d.mkdir(exist_ok=True)
    p = d / "headroom-backup-2026-01-01T00-00-00Z.tar.gz"
    p.write_bytes(b"tarball-bytes")
    return p


async def test_upload_hook_noop_when_unset(tmp_path, monkeypatch):
    """No command configured → does nothing, raises nothing."""
    monkeypatch.delenv("HEADROOM_BACKUP_UPLOAD_CMD", raising=False)
    backup = _fake_backup(tmp_path)
    await backup_service._run_upload_hook(backup)
    # Nothing else was created next to the backup.
    assert list(backup.parent.iterdir()) == [backup]


async def test_upload_hook_runs_command_with_substituted_placeholders(tmp_path, monkeypatch):
    """A real subprocess proves {path}/{dir}/{name} expand to the actual file."""
    backup = _fake_backup(tmp_path)
    monkeypatch.setenv("HEADROOM_BACKUP_UPLOAD_CMD", "cp {path} {dir}/uploaded-{name}")
    await backup_service._run_upload_hook(backup)
    shipped = backup.parent / f"uploaded-{backup.name}"
    assert shipped.read_bytes() == b"tarball-bytes"  # the real bytes, not a rename


async def test_upload_hook_failure_is_swallowed(tmp_path, monkeypatch):
    """A non-zero exit (e.g. rclone auth failure) must not raise."""
    monkeypatch.setenv("HEADROOM_BACKUP_UPLOAD_CMD", "false")
    await backup_service._run_upload_hook(_fake_backup(tmp_path))  # no exception


async def test_upload_hook_missing_binary_is_swallowed(tmp_path, monkeypatch):
    """A missing uploader binary (rclone not installed) must not raise."""
    monkeypatch.setenv(
        "HEADROOM_BACKUP_UPLOAD_CMD", "headroom-no-such-binary-xyz {path}"
    )
    await backup_service._run_upload_hook(_fake_backup(tmp_path))  # no exception


async def test_upload_hook_timeout_is_swallowed(tmp_path, monkeypatch):
    """A hanging uploader is killed at the timeout, not left to block forever."""
    monkeypatch.setenv("HEADROOM_BACKUP_UPLOAD_CMD", "sleep 5")
    monkeypatch.setenv("HEADROOM_BACKUP_UPLOAD_TIMEOUT", "0.2")
    await backup_service._run_upload_hook(_fake_backup(tmp_path))  # returns promptly


async def test_scheduled_backup_ships_off_box_and_local_survives(tmp_path, monkeypatch):
    """End-to-end: a scheduled backup is written locally AND copied off-box; an
    upload that runs does not stop the local backup from succeeding."""
    dest = tmp_path / "offsite"
    dest.mkdir()
    monkeypatch.setenv("HEADROOM_BACKUP_UPLOAD_CMD", f"cp {{path}} {dest}/{{name}}")

    result = await backup_service.write_scheduled_backup(retention=7)

    assert result is not None and result.exists()   # local backup intact
    assert (dest / result.name).exists()             # shipped off-box


async def test_scheduled_backup_survives_broken_uploader(tmp_path, monkeypatch):
    """A failing upload command still yields a successful local backup path."""
    monkeypatch.setenv("HEADROOM_BACKUP_UPLOAD_CMD", "false")
    result = await backup_service.write_scheduled_backup(retention=7)
    assert result is not None and result.exists()
