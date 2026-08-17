"""The scheduled-backup loop must outlive its own failures.

It previously ran the startup age-check and first backup ABOVE its try block,
and caught only `CancelledError` inside it. So one unwritable `/data` at boot,
or a single transient "database is locked", ended the task for the entire life
of the process — and because nothing supervised it and nothing reported it, the
symptom was backups silently never happening again while the UI kept cheerfully
listing the last successful one. For the feature that IS the disaster-recovery
story, that is the worst available failure mode.
"""

from __future__ import annotations

import asyncio

import pytest

from headroom.services import backup_service

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _fresh_health():
    """Health is process-global; don't let one test's failures leak into another."""
    backup_service._health = backup_service.BackupHealth()
    yield
    backup_service._health = backup_service.BackupHealth()


# Captured before any test patches `asyncio.sleep`. A stub that calls
# `asyncio.sleep` by name would invoke the patched version and recurse forever.
_REAL_SLEEP = asyncio.sleep


def _instant_sleep(monkeypatch):
    """Make the loop's inter-backup wait a no-op so it spins at full speed."""
    monkeypatch.setattr(asyncio, "sleep", lambda *_a, **_k: _REAL_SLEEP(0))


async def _run_briefly(coro_fn, ticks: int = 3):
    """Run the loop, let it turn over a few times, then cancel it."""
    task = asyncio.create_task(coro_fn())
    for _ in range(ticks * 10):
        await _REAL_SLEEP(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_a_failing_backup_does_not_kill_the_scheduler(monkeypatch):
    """The whole point: attempt N+1 must still happen after attempt N raises."""
    attempts = 0

    async def boom(retention):
        nonlocal attempts
        attempts += 1
        raise OSError("read-only file system")

    monkeypatch.setattr(backup_service, "write_scheduled_backup", boom)
    monkeypatch.setattr(
        backup_service, "_seconds_since_newest_backup_sync", lambda: None
    )
    _instant_sleep(monkeypatch)

    await _run_briefly(lambda: backup_service.scheduled_backup_loop(24.0, 7))

    assert attempts > 1, "the loop died on the first failure instead of retrying"
    assert backup_service.health().consecutive_failures > 1
    assert "read-only file system" in (backup_service.health().last_error or "")


async def test_a_failure_at_startup_does_not_kill_the_scheduler(monkeypatch):
    """The original bug precisely: the boot-time age check was outside the try.

    An unmounted or read-only `/data` at boot — the realistic Pi failure — made
    this raise before the loop was ever entered.
    """
    attempts = 0

    def exploding_age_check():
        raise PermissionError("/data not writable")

    async def ok(retention):
        nonlocal attempts
        attempts += 1

    monkeypatch.setattr(
        backup_service, "_seconds_since_newest_backup_sync", exploding_age_check
    )
    monkeypatch.setattr(backup_service, "write_scheduled_backup", ok)
    _instant_sleep(monkeypatch)

    await _run_briefly(lambda: backup_service.scheduled_backup_loop(24.0, 7))

    assert attempts > 0, "a boot-time failure permanently disabled backups"


async def test_recovery_clears_the_failure_state(monkeypatch):
    """A scheduler that recovers must stop reporting itself as broken."""
    calls = 0

    async def fail_once_then_work(retention):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("transient")

    monkeypatch.setattr(backup_service, "write_scheduled_backup", fail_once_then_work)
    monkeypatch.setattr(
        backup_service, "_seconds_since_newest_backup_sync", lambda: None
    )
    _instant_sleep(monkeypatch)

    await _run_briefly(lambda: backup_service.scheduled_backup_loop(24.0, 7))

    health = backup_service.health()
    assert health.consecutive_failures == 0
    assert health.last_error is None
    assert health.last_success_at is not None


async def test_startup_skips_a_backup_when_a_recent_one_exists(monkeypatch):
    """Restart loops must not spam same-hour backups — the old history bug."""
    attempts = 0

    async def count(retention):
        nonlocal attempts
        attempts += 1

    # Newest snapshot is 60s old against a 24h interval: nowhere near due.
    monkeypatch.setattr(
        backup_service, "_seconds_since_newest_backup_sync", lambda: 60.0
    )
    monkeypatch.setattr(backup_service, "write_scheduled_backup", count)

    task = asyncio.create_task(backup_service.scheduled_backup_loop(24.0, 7))
    for _ in range(20):
        await _REAL_SLEEP(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert attempts == 0, "a fresh restart wrote a redundant startup backup"


async def test_health_endpoint_reports_a_dead_scheduler(client):
    """`running` must distinguish "no backups coming" from "none yet"."""
    resp = await client.get("/api/admin/backups/health")

    assert resp.status_code == 200
    body = resp.json()
    # Backups are disabled in tests, so no task exists — which must read as
    # not-running rather than as healthy.
    assert body["running"] is False
    assert body["consecutive_failures"] == 0
