"""rsync destinations are directories, and rsync children are never abandoned.

rsync copying ONE file reads a destination whose last element is not an
existing directory, and has no trailing slash, as the new FILENAME. Every
example this app gives names a folder that does not exist yet, so each night's
archive overwrote a single regular file called `headroom` — rc=0 every time,
so the off-site card stayed green over a remote holding one archive and no
history.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from pathlib import Path

import pytest

from headroom.services import backup_service, settings_service

pytestmark = pytest.mark.anyio


async def _argv_for(db_session, provider: str, dest: str) -> list[str]:
    await settings_service.set_setting(db_session, backup_service.UPLOAD_PROVIDER_KEY, provider)
    await settings_service.set_setting(db_session, backup_service.UPLOAD_DESTINATION_KEY, dest)
    await db_session.commit()
    argv = await backup_service.resolve_upload_argv(
        db_session, Path("/data/backups/headroom-backup-x.tar.gz")
    )
    assert argv is not None
    return argv


@pytest.mark.parametrize(
    ("provider", "dest", "expected"),
    [
        # The shipped examples, exactly as the UI and docs give them.
        ("rsync", "pi@nas.local:/volume1/backups/headroom", "pi@nas.local:/volume1/backups/headroom/"),
        ("synology", "backup@nas.local::backups/headroom", "backup@nas.local::backups/headroom/"),
        # A bare module is the module's root — a directory either way.
        ("synology", "backup@nas.local::backups", "backup@nas.local::backups/"),
        # Already spelled as a directory: left exactly as typed.
        ("rsync", "pi@nas.local:/volume1/backups/", "pi@nas.local:/volume1/backups/"),
        # An EMPTY path is the remote home. A slash would make it `:/`, the ROOT.
        ("rsync", "pi@nas.local:", "pi@nas.local:"),
    ],
)
async def test_an_rsync_destination_reaches_argv_as_a_directory(
    client, db_session, provider, dest, expected
):
    argv = await _argv_for(db_session, provider, dest)
    assert argv[-1] == expected


async def test_an_rclone_destination_is_left_as_typed(client, db_session):
    """`rclone copy` always copies INTO its destination; a slash buys nothing."""
    argv = await _argv_for(db_session, "rclone", "box:Headroom-Backups")
    assert argv[-1] == "box:Headroom-Backups"


@pytest.mark.skipif(shutil.which("rsync") is None, reason="needs an rsync binary")
async def test_two_nights_of_backups_are_two_archives_not_one_file(tmp_path):
    """The failure itself, against a real rsync.

    Runs the SHIPPED argv template twice, with a destination folder that does
    not exist yet — the state every first upload is in.
    """
    src = tmp_path / "local"
    src.mkdir()
    nights = []
    for name in ("headroom-backup-2026-09-01T00-00-00Z.tar.gz",
                 "headroom-backup-2026-09-02T00-00-00Z.tar.gz"):
        archive = src / name
        archive.write_bytes(name.encode())
        nights.append(archive)
    remote = tmp_path / "nas" / "backups" / "headroom"
    remote.parent.mkdir(parents=True)

    spec = backup_service.UPLOAD_PROVIDERS["rsync"]
    dest = backup_service._as_directory(str(remote)) if spec.dest_is_directory else str(remote)
    for archive in nights:
        argv = [t.replace("{path}", str(archive)).replace("{dest}", dest) for t in spec.argv]
        subprocess.run(argv, check=True, capture_output=True)  # fixed argv, no shell

    assert remote.is_dir(), "the destination became a FILE named after the folder"
    assert sorted(p.name for p in remote.iterdir()) == [a.name for a in nights]


# ---- list_rsync_modules reaps what it starts ---------------------------- #


async def test_a_module_listing_that_times_out_kills_its_rsync(tmp_path, monkeypatch):
    """`wait_for` stops WAITING; it does not stop the child.

    The sibling `_run_upload_hook` kills and reaps on timeout. This returned
    [] and left the rsync running — one orphan per "Test now" against an
    unreachable NAS.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    pidfile = tmp_path / "rsync.pid"
    fake = bindir / "rsync"
    fake.write_text(f'#!/bin/sh\necho $$ > "{pidfile}"\nexec sleep 30\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(backup_service, "_RSYNC_LIST_GRACE_S", 0.0)

    try:
        modules = await backup_service.list_rsync_modules("u@nas.invalid::m/p", timeout=0.5)
        assert modules == []
        pid = int(pidfile.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)  # signal 0: "does it exist?"
    finally:
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass
