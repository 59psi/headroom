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
    # Own subdir so "nothing else was created" assertions stay airtight, and
    # the real name builder so this keeps matching an actual backup filename.
    d = tmp_path / "bk"
    d.mkdir(exist_ok=True)
    p = d / backup_service._timestamped_name()
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


@pytest.mark.parametrize(
    ("cmd", "timeout"),
    [
        ("false", None),                                # non-zero exit (auth failure)
        ("headroom-no-such-binary-xyz {path}", None),   # uploader not installed
        ("sleep 5", "0.2"),                             # hangs → killed at timeout
    ],
    ids=["nonzero-exit", "missing-binary", "timeout"],
)
async def test_upload_hook_never_raises_and_records_the_failure(
    tmp_path, monkeypatch, cmd, timeout
):
    """However the uploader fails, the hook returns quietly — and RECORDS it.

    The local backup is already safely on disk — an off-box copy that blows up
    (or hangs) must never propagate into the scheduler loop. But "returned
    quietly" is only half the contract: `BackupHealth.record_upload` exists so
    an owner can see the nightly copy has been failing, and this test used to
    assert nothing at all, so a hook that swallowed the failure without
    recording it passed.
    """
    monkeypatch.setenv("HEADROOM_BACKUP_UPLOAD_CMD", cmd)
    if timeout:
        monkeypatch.setenv("HEADROOM_BACKUP_UPLOAD_TIMEOUT", timeout)
    before = backup_service.health().upload_failures
    await backup_service._run_upload_hook(_fake_backup(tmp_path))
    health = backup_service.health()
    assert health.last_upload_ok is False
    assert health.upload_failures == before + 1
    assert health.last_upload_error, "the reason is what makes the record actionable"


async def test_scheduled_backup_ships_off_box_and_local_survives(tmp_path, monkeypatch):
    """End-to-end: a scheduled backup is written locally AND copied off-box; an
    upload that runs does not stop the local backup from succeeding."""
    dest = tmp_path / "offsite"
    dest.mkdir()
    monkeypatch.setenv("HEADROOM_BACKUP_UPLOAD_CMD", f"cp {{path}} {dest}/{{name}}")

    result = await backup_service.write_scheduled_backup(keep=7)

    assert result is not None and result.exists()   # local backup intact
    assert (dest / result.name).exists()             # shipped off-box


async def test_scheduled_backup_survives_broken_uploader(tmp_path, monkeypatch):
    """A failing upload command still yields a successful local backup path."""
    monkeypatch.setenv("HEADROOM_BACKUP_UPLOAD_CMD", "false")
    result = await backup_service.write_scheduled_backup(keep=7)
    assert result is not None and result.exists()
