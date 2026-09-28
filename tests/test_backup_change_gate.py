"""Backups are written when the data changed, and only the newest N are kept.

Two changes that only make sense together. Writing a fresh tarball every day
of an untouched collection re-reads every photo, wears the SD card, and — with
a fixed-size window — evicts real history to store a restatement of what is
already on disk.

The pairing also closes a trap: age-based pruning plus change-gating has a
steady state of ZERO backups on an idle system, because the last one ages out
with nothing being written to replace it. Counting cannot do that.
"""

from __future__ import annotations

import pytest

from headroom.services import backup_service

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _fresh_health():
    backup_service._health = backup_service.BackupHealth()
    yield
    backup_service._health = backup_service.BackupHealth()


async def test_an_unchanged_collection_produces_the_same_fingerprint():
    first = backup_service._data_fingerprint_sync()
    second = backup_service._data_fingerprint_sync()

    assert first == second


async def test_a_new_photo_changes_the_fingerprint():
    from headroom.config import settings

    before = backup_service._data_fingerprint_sync()
    (settings.upload_dir / "hats" / "new-hat.png").write_bytes(b"pretend png")

    assert backup_service._data_fingerprint_sync() != before


async def test_an_unreadable_database_falls_back_to_the_file_and_its_wal(monkeypatch, tmp_path):
    """When the rows cannot be read, the gate judges the FILES — and both of
    them: in WAL mode a commit can leave `headroom.db` completely untouched,
    and watching the main file alone would report a day of edits as "no
    changes", whose consequence is a backup that never runs."""
    db = tmp_path / "headroom.db"
    db.write_bytes(b"not a database")
    wal = tmp_path / "headroom.db-wal"
    wal.write_bytes(b"")
    monkeypatch.setattr(backup_service, "_db_path", lambda: db)

    before = backup_service._data_fingerprint_sync()
    wal.write_bytes(b"a committed transaction")

    assert backup_service._data_fingerprint_sync() != before


async def _seed_priced_hat(factory) -> int:
    from datetime import datetime, timezone

    from headroom.models.hat import Hat

    async with factory() as db:
        hat = Hat(
            brand="melin", model_name="Odysea Hydro", style="cap", condition="excellent",
            size="classic", resale_price=80.0,
            updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        db.add(hat)
        await db.commit()
        return hat.id


async def test_a_sweep_that_moved_nothing_and_a_restart_leave_the_gate_closed(
    file_engine, monkeypatch
):
    """The gate answered "changed" from the database FILE, which a re-pricing
    sweep (stamping every hat it consults) and a stop/start (the shutdown
    checkpoint) both rewrite — so with re-pricing on, every daily cycle wrote
    a full tarball and KEEP=5 covered five days, not five changes."""
    from pathlib import Path

    from sqlalchemy import text

    from headroom.services import hat_analysis_pipeline, repricing

    engine, factory = file_engine
    monkeypatch.setattr(backup_service, "_db_path", lambda: Path(engine.url.database))
    await _seed_priced_hat(factory)
    after_backup = backup_service._data_fingerprint_sync()

    async def consulted_unchanged(hat):
        return hat_analysis_pipeline.RESALE_PRICED

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", consulted_unchanged)
    monkeypatch.setenv("HEADROOM_REPRICING_DELAY_SECONDS", "0")
    assert await repricing.reprice_once(factory) == (0, 1)
    async with factory() as db:
        await db.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))

    assert backup_service._data_fingerprint_sync() == after_backup


async def test_a_real_edit_still_opens_the_gate(file_engine, monkeypatch):
    from pathlib import Path

    from headroom.models.hat import Hat

    engine, factory = file_engine
    monkeypatch.setattr(backup_service, "_db_path", lambda: Path(engine.url.database))
    hat_id = await _seed_priced_hat(factory)
    before = backup_service._data_fingerprint_sync()

    async with factory() as db:
        hat = await db.get(Hat, hat_id)
        hat.resale_price = 95.0
        await db.commit()

    assert backup_service._data_fingerprint_sync() != before


async def test_the_marker_is_not_stored_in_the_database():
    """It measures the database, so storing it there would defeat it.

    Writing the fingerprint into `app_settings` would modify the very file
    being fingerprinted, so the next cycle would always see a change and the
    gate would never once close.
    """
    path = backup_service._fingerprint_path()

    assert path.parent.name == backup_service.BACKUP_DIR_NAME
    assert path.suffix != ".db"


async def test_a_second_cycle_with_no_changes_writes_nothing(monkeypatch):
    """The point of the feature."""
    import asyncio

    calls: list[str | None] = []

    async def _write(keep, fingerprint=None):
        calls.append(fingerprint)
        backup_service._write_fingerprint_sync(fingerprint)  # what the real one does
        return backup_service._backup_dir() / "fake.tar.gz"

    monkeypatch.setattr(backup_service, "write_scheduled_backup", _write)
    monkeypatch.setattr(backup_service, "_seconds_since_newest_backup_sync", lambda: None)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda *_a, **_k: real_sleep(0))

    task = asyncio.create_task(backup_service.scheduled_backup_loop(24.0, 5))
    for _ in range(60):
        await real_sleep(0.002)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(calls) == 1, "an unchanged collection was backed up more than once"
    assert backup_service.health().last_skip_reason is not None


async def test_a_skipped_cycle_still_counts_as_an_attempt():
    """Otherwise an idle collection is indistinguishable from a dead task.

    `last_attempt_at` freezing is the exact symptom of the scheduler dying,
    which is what this whole health record exists to make visible.
    """
    health = backup_service.health()
    assert health.last_attempt_at is None

    health.record_skipped("No changes since the last backup.")

    assert health.last_attempt_at is not None
    assert health.last_success_at is None  # a skip is not a success
    assert health.consecutive_failures == 0


async def test_a_skip_does_not_clear_a_standing_failure():
    """Skipping is not recovery. Only a written backup is."""
    health = backup_service.health()
    health.record_failure("disk full")

    health.record_skipped("No changes since the last backup.")

    assert health.consecutive_failures == 1
    assert health.last_error is not None


async def test_the_skip_reason_reaches_the_api(client):
    backup_service.health().record_skipped("No changes since the last backup.")

    body = (await client.get("/api/admin/backups/health")).json()

    assert body["last_skip_reason"] == "No changes since the last backup."


async def test_keep_defaults_to_five(monkeypatch):
    monkeypatch.delenv("HEADROOM_BACKUP_KEEP", raising=False)
    monkeypatch.delenv("HEADROOM_BACKUP_RETENTION_DAYS", raising=False)

    assert backup_service.backup_keep() == 5


async def test_the_deprecated_days_variable_is_read_as_a_count(monkeypatch):
    """An existing `.env` should keep meaning something rather than reverting.

    The unit changed, so the name is deprecated — but silently ignoring a
    value someone deliberately set is worse than honoring it under its new
    meaning and saying so in the docs.
    """
    monkeypatch.delenv("HEADROOM_BACKUP_KEEP", raising=False)
    monkeypatch.setenv("HEADROOM_BACKUP_RETENTION_DAYS", "9")

    assert backup_service.backup_keep() == 9


async def test_keep_wins_over_the_deprecated_name(monkeypatch):
    monkeypatch.setenv("HEADROOM_BACKUP_KEEP", "3")
    monkeypatch.setenv("HEADROOM_BACKUP_RETENTION_DAYS", "9")

    assert backup_service.backup_keep() == 3
