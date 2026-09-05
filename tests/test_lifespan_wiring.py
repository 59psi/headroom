"""The lifespan, booted for real, against a database with production semantics.

Until 2.77.2 no test ran it. `conftest` said so in a comment ("it doesn't run
under ASGITransport") and one test read the lifespan's SOURCE TEXT with
`inspect.getsource` to check the order of a tuple, which is the closest
anything came. So the one function that wires the application together — which
loops start, which one-time backfills run, what the health records are seeded
with, what shutdown cancels — was the one function the suite never executed.
Every service it calls had tests. Nothing proved the lifespan called them.

The reason was structural, not laziness: the lifespan reached for the
module-level `async_session` in five places and `init_db()` on the module
engine, both bound to `settings.database_url` — under test, `./headroom.db` in
the working directory. Booting it would have created a real file. It now takes
`app.state.session_factory` and `app.state.engine`, the same seam the auth
gate and `error_handler` already used, and the conftest points the module
engine at an unopenable path so a regression raises rather than writing files.

**These tests use a file-backed SQLite, not the suite's in-memory one.** The
in-memory engine is a `StaticPool`: one connection shared by every session.
That is fine for a request test, which holds one session at a time, and wrong
for a boot, which has the prune loop, two backfills and a worker all open at
once — one session's `close()` issues `ROLLBACK` on the shared connection and
discards another's uncommitted `UPDATE` before its `COMMIT`. Measured: a
re-queued hat that the worker processed and committed stayed `pending`, with
no error anywhere, because the prune loop closed its session in between. A
file gives each session its own connection, which is what production has, and
the connect hook from `database.py` is attached so WAL / busy_timeout /
synchronous=FULL are the real ones too.

Each test boots through `app.router.lifespan_context` and asserts an outcome:
a record that was written, a task that exists or does not, a file that
appeared, a call that happened in an order.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from headroom import database
from headroom.config import settings
from headroom.models.app_setting import AppSetting
from headroom.models.room import Room
from headroom.models.user import AuthSession, User
from headroom.services import (
    activity_service,
    analysis_queue,
    auth_service,
    import_service,
    repricing,
)
from headroom.services.task_health import TaskHealth

pytestmark = pytest.mark.anyio

#: Every one-time data repair the lifespan runs, by the flag it leaves behind.
#: A fifth repair with no flag would run on every boot; a renamed flag would
#: re-run a repair on an upgraded install. Both are worth a failing test.
ONE_TIME_FLAGS = (
    "vocabulary_merged_v1",
    "retail_prices_v2",
    "model_names_split_v1",
    "color_names_normalized_v1",
)

_SESSION_ID = "boot-test-session"


# --------------------------------------------------------------------------
# fixtures: a file-backed database and an app wired to it
# --------------------------------------------------------------------------


@pytest.fixture
async def boot_db(tmp_path):
    """A real SQLite file with the production connect hook, tables created.

    Tables are created here rather than left to `init_db` because several
    tests seed crash-stranded state BEFORE boot; `init_db` then runs against
    an already-populated schema, which is also what an upgrade looks like.
    """
    url = f"sqlite+aiosqlite:///{tmp_path / 'boot.db'}"
    engine = create_async_engine(url, echo=False)
    event.listen(engine.sync_engine, "connect", database._sqlite_pragmas)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(database.Base.metadata.create_all)
    async with factory() as db:
        db.add(Room(id=1, name="Default Room", is_default=True))
        await db.commit()
    yield engine, factory
    await engine.dispose()


@pytest.fixture
def app(boot_db):
    """Overrides the conftest `app` for this module: same shape, file database."""
    from headroom.app import create_app

    engine, factory = boot_db
    app = create_app()

    async def override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[database.get_db] = override_get_db
    app.state.session_factory = factory
    app.state.engine = engine
    return app


@pytest.fixture
async def client(app, boot_db):
    """Authenticated client against the file database."""
    _, factory = boot_db
    async with factory() as db:
        user = User(
            username="bootowner",
            password_hash=auth_service.hash_password("boot-test-password"),
            api_token="hr_boot-test-token",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        db.add(AuthSession(
            id=_SESSION_ID, user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        ))
        await db.commit()
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    c.cookies.set("headroom_session", _SESSION_ID)
    return c


@pytest.fixture(autouse=True)
def _fresh_process_state():
    """Module-level records the lifespan writes into, reset around each boot.

    They are process-local by design (see `RepricingHealth`); a test that
    booted once and left `last_success_at` set would make the next boot's
    assertion pass without the loop having run.
    """
    from headroom.services import backup_service

    def reset():
        activity_service.retention_health = TaskHealth(name="retention prune")
        repricing._health = repricing.RepricingHealth()
        repricing.release_full_sweep()
        backup_service._health = backup_service.BackupHealth()
        backup_service._upload_state_loaded = False

    reset()
    yield
    reset()


async def _boot(app):
    """The real thing — not a fixture, so a test can boot twice."""
    return app.router.lifespan_context(app)


async def _flags(db):
    rows = (await db.execute(
        select(AppSetting).where(AppSetting.key.in_(ONE_TIME_FLAGS))
    )).scalars().all()
    return {r.key: r.value for r in rows}


async def _wait_for(predicate, *, timeout=5.0, what="condition"):
    """Poll a predicate with real waits — `sleep(0)` is not a wait.

    Background loops here do their first iteration on aiosqlite's worker
    thread; yielding to the event loop does not wait for that thread.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.02)


async def _settled(app):
    """Wait for the boot-time work before shutting down.

    On the real box the first prune pass and the backfills ARE part of boot; a
    test that exits the instant the context opens is testing a shutdown that
    never happens. The one-shot tasks are awaited by handle; the prune through
    the record it writes, which is the only thing its infinite loop exposes.
    """
    await asyncio.gather(*app.state.boot_tasks)
    await _wait_for(
        lambda: activity_service.retention_health.last_attempt_at is not None,
        what="the boot-time retention prune",
    )


# --------------------------------------------------------------------------
# boot and shutdown
# --------------------------------------------------------------------------


async def test_the_lifespan_boots_and_leaves_no_task_behind(app, boot_db):
    """Enter, exit, and account for every task.

    A loop that survives shutdown keeps a session factory alive and, on the
    real box, keeps writing after `compose down` has decided it is safe to
    stop — the WAL-checkpoint ordering below exists for exactly that window.
    """
    _, factory = boot_db
    before = set(asyncio.all_tasks())

    async with await _boot(app):
        started = set(asyncio.all_tasks()) - before
        assert started, "boot started no background work at all"
        assert set(app.state.boot_tasks) <= started
        await _settled(app)

    for task in started:
        assert task.done(), f"background task survived shutdown: {task.get_name()}"

    # And `init_db` plus the backfills ran against THIS database.
    async with factory() as db:
        assert set(await _flags(db)) == set(ONE_TIME_FLAGS)


async def test_boot_seeds_the_default_branding_into_the_upload_dir(app):
    """`_seed_branding` — 24% of `app.py` was this and its siblings, unexecuted."""
    async with await _boot(app):
        logo = Path(settings.upload_dir) / "branding" / "logo.png"
        assert logo.is_file(), "the bundled logo was not seeded on first boot"
        # Idempotent: a user-uploaded logo must survive a restart.
        logo.write_bytes(b"the owner's own logo")
        await _settled(app)
    async with await _boot(app):
        assert logo.read_bytes() == b"the owner's own logo", (
            "a restart overwrote the owner's logo with the bundled default"
        )
        await _settled(app)


# --------------------------------------------------------------------------
# one-time backfills
# --------------------------------------------------------------------------


async def test_boot_stamps_every_one_time_backfill_and_does_not_repeat_them(app, boot_db, monkeypatch):
    """Four repairs, each guarded by a flag, each run exactly once.

    The second half is the one that matters on the real box: a repair that
    re-ran on every boot would re-price or rename the collection daily. The
    color normalizer is the probe because it is the cheapest to count; the
    property is the flags, which cover all four.
    """
    from headroom.services import hat_service

    _, factory = boot_db
    calls = []
    real = hat_service.normalize_existing_colors

    async def counting(db):
        calls.append(1)
        return await real(db)

    monkeypatch.setattr(hat_service, "normalize_existing_colors", counting)

    async with await _boot(app):
        await _settled(app)
    async with factory() as db:
        assert await _flags(db) == {flag: "done" for flag in ONE_TIME_FLAGS}
    assert calls == [1], "the first boot must run the repair exactly once"

    async with await _boot(app):
        await _settled(app)
    assert calls == [1], "a second boot re-ran a one-time repair"


# --------------------------------------------------------------------------
# the retention prune — the health record that shipped with no test
# --------------------------------------------------------------------------


async def test_boot_runs_the_retention_prune_and_the_endpoint_reports_it(app, client):
    """Loop -> record -> route, end to end.

    2.77.0 added `retention_health`, the `record_success` call in the loop,
    and `GET /api/admin/activity-log/retention`. Coverage afterwards:
    `TaskHealth.record_success` never executed, the route body never executed.
    The loop prunes first and sleeps after, so the record must exist the
    moment boot returns — and the endpoint must be the thing that serves it.
    """
    async with await _boot(app):
        health = activity_service.retention_health
        await _wait_for(lambda: health.last_attempt_at is not None, what="the first prune")

        assert health.last_success_at is not None, health.last_error
        assert health.consecutive_failures == 0
        assert health.last_error is None

        body = (await client.get("/api/admin/activity-log/retention")).json()
        assert body["retention_days"] == activity_service.retention_days()
        assert body["health"]["last_success_at"] == health.last_success_at.isoformat()
        assert body["health"]["consecutive_failures"] == 0
        await _settled(app)


async def test_a_failing_prune_is_recorded_not_swallowed(app, monkeypatch):
    """The other half of the record: a loop that dies must say so.

    Before the record existed this was one WARNING per day into a container
    log while two tables grew without bound. The point of the record is that
    the failure is READABLE; this is the test that it gets written.
    """
    async def boom(db):
        raise RuntimeError("retention exploded")

    monkeypatch.setattr(activity_service, "prune_activity", boom)

    async with await _boot(app):
        health = activity_service.retention_health
        await _wait_for(lambda: health.last_attempt_at is not None, what="the first prune")

        assert health.consecutive_failures == 1
        assert health.last_success_at is None
        assert "retention exploded" in (health.last_error or "")
        await asyncio.gather(*app.state.boot_tasks)


# --------------------------------------------------------------------------
# workers and schedulers: the env gates, both directions
# --------------------------------------------------------------------------


async def test_disabled_workers_are_not_started(app):
    """The conftest turns every worker off. Boot must honor that, and record it.

    `None` on `app.state`, not a task that exits early: the admin API reads
    these to answer "is the scheduler alive", and a task that started and
    immediately finished would answer that question wrongly in both
    directions over its short life.
    """
    async with await _boot(app):
        assert app.state.backup_task is None
        assert app.state.repricing_task is None
        assert import_service.worker_alive() is False
        assert analysis_queue.worker_alive() is False
        await _settled(app)


async def test_the_repricing_scheduler_runs_its_first_sweep_against_the_app_database(app, monkeypatch):
    """Enabled, the scheduler must start — and must sweep the RIGHT database.

    This is the discriminating test for the seam. `reprice_once` took a
    session factory for exactly this reason, and the scheduler's own loop
    never passed one; it swept the module-level database. With the factory
    forwarded, the first sweep finds this database's zero hats and records a
    success. Without it, the module engine points at an unopenable path under
    test and the sweep records a failure instead — so the assertion below
    cannot pass by accident.
    """
    monkeypatch.setenv("HEADROOM_REPRICING_ENABLED", "true")

    async with await _boot(app):
        task = app.state.repricing_task
        assert isinstance(task, asyncio.Task) and not task.done()

        health = repricing._health
        await _wait_for(lambda: health.last_run_at is not None, what="the first sweep")

        assert health.last_error is None, (
            f"the scheduled sweep did not use the app's session factory: {health.last_error}"
        )
        assert health.last_success_at is not None
        assert health.last_considered == 0, "this database holds no hats"
        await _settled(app)

    assert task.done(), "the scheduler outlived shutdown"


async def test_the_import_worker_boots_and_heals_a_crash_stranded_item(app, boot_db, monkeypatch):
    """`HEADROOM_IMPORT_WORKER_ENABLED=true` → worker alive, boot sweep ran, here.

    An item left `processing` by a crash is the case `_recover_on_boot` exists
    for. Seeded BEFORE boot; if the worker were opening the module-level
    session instead of the app's it would not find this row — and under the
    conftest guard it would not open at all.
    """
    import json

    from headroom.models.import_job import ImportJob, ImportJobItem

    _, factory = boot_db
    monkeypatch.setenv("HEADROOM_IMPORT_WORKER_ENABLED", "true")
    async with factory() as db:
        job = ImportJob(total=1, status="running", defaults_json=json.dumps({}))
        db.add(job)
        await db.commit()
        db.add(ImportJobItem(job_id=job.id, filename="stranded.jpg", status="processing", bytes=1))
        await db.commit()
        job_id = job.id

    async with await _boot(app):
        assert import_service.worker_alive(), "the import worker was not started"

        async def statuses():
            async with factory() as db:
                return (await db.execute(
                    select(ImportJobItem.status).where(ImportJobItem.job_id == job_id)
                )).scalars().all()

        # The sweep resets it to `queued` and the loop then consumes it — with no
        # staged file it errors, which is the worker's own tests' business. What
        # this asserts is that boot LOOKED at the app's rows and acted on them.
        deadline = asyncio.get_running_loop().time() + 5
        while "processing" in await statuses():
            assert asyncio.get_running_loop().time() < deadline, "item still stranded in 'processing'"
            await asyncio.sleep(0.02)
        await _settled(app)

    assert not import_service.worker_alive(), "shutdown left the import worker running"


async def test_the_analysis_worker_boots_and_requeues_a_pending_hat(app, boot_db, client, monkeypatch):
    """`HEADROOM_ANALYSIS_WORKER_ENABLED=true` → worker alive, pending hat picked up.

    A hat left `pending` by a crash is re-queued by `_recover_on_boot`. It has
    no photo, so the worker marks it failed — that path is tested elsewhere;
    here the point is that it left `pending` at all, which it can only do if
    the worker found it in THIS database and its commit was not rolled back by
    a neighboring session (the StaticPool failure that moved this module onto
    a file).
    """
    from headroom.models.hat import Hat

    _, factory = boot_db
    monkeypatch.setenv("HEADROOM_ANALYSIS_WORKER_ENABLED", "true")
    hat_id = (await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )).json()["id"]
    async with factory() as db:
        hat = await db.get(Hat, hat_id)
        hat.analysis_status = "pending"
        await db.commit()

    async with await _boot(app):
        assert analysis_queue.worker_alive(), "the analysis worker was not started"

        async def status():
            async with factory() as db:
                return (await db.execute(
                    select(Hat.analysis_status).where(Hat.id == hat_id)
                )).scalar_one()

        deadline = asyncio.get_running_loop().time() + 5
        while await status() == "pending":
            assert asyncio.get_running_loop().time() < deadline, "hat still 'pending' after boot"
            await asyncio.sleep(0.02)
        assert await status() == "error"
        await _settled(app)

    assert not analysis_queue.worker_alive(), "shutdown left the analysis worker running"


async def test_the_backup_scheduler_boots_writes_a_backup_and_resolves_its_upload_here(
    app, monkeypatch, tmp_path,
):
    """`HEADROOM_BACKUP_ENABLED=true` → task alive, first cycle written, hook ran.

    The discriminating half is the upload hook. It resolves its argv from the
    database on every cycle, and used to do so through a local import of the
    module-level `async_session`. With no upload configured that resolves to
    None and records nothing — `last_upload_ok is None`. With the seam
    dropped, the module engine is unopenable under test, the hook's own
    `except` records a FAILED upload, and this assertion cannot pass.
    """
    from headroom.services import backup_service

    monkeypatch.setenv("HEADROOM_BACKUP_ENABLED", "true")
    db_file = tmp_path / "snapshot-source.db"
    db_file.write_bytes(b"sqlite stand-in")
    monkeypatch.setattr(backup_service, "_db_path", lambda: db_file)

    def _copy_snapshot(db, dest_dir):
        out = dest_dir / db.name
        out.write_bytes(db.read_bytes())
        return out

    monkeypatch.setattr(backup_service, "_snapshot_db_sync", _copy_snapshot)

    async with await _boot(app):
        task = app.state.backup_task
        assert isinstance(task, asyncio.Task) and not task.done(), "the scheduler was not started"

        health = backup_service._health
        await _wait_for(lambda: health.last_attempt_at is not None, what="the first backup cycle")

        assert health.last_error is None, health.last_error
        assert health.last_success_at is not None, health.last_skip_reason
        assert list(backup_service._backup_dir().glob("headroom-backup-*.tar.gz")), (
            "the first cycle recorded success and wrote nothing"
        )
        assert health.last_upload_ok is None, (
            f"the upload hook did not resolve through the app's database: {health.last_upload_error}"
        )
        await _settled(app)

    assert task.done(), "the scheduler outlived shutdown"


# --------------------------------------------------------------------------
# shutdown order
# --------------------------------------------------------------------------


async def test_shutdown_stops_workers_then_checkpoints_the_wal_last(app, boot_db, monkeypatch):
    """Replaces a test that parsed this tuple out of the lifespan's source.

    The order is load-bearing: the import and analysis workers still commit
    as they wind down, so a checkpoint before them leaves exactly the writes
    made during shutdown in the WAL — the ones a power cut right after
    `compose down` would find. The old test asserted the order by reading the
    file. This one boots the app and records what it actually did — and that
    the checkpoint ran on THIS app's engine, not the module's.
    """
    from headroom import app as app_module
    from headroom.services import mdns_service

    engine, _ = boot_db
    calls: list[tuple[str, object]] = []

    def recorder(name):
        async def _rec(*args):
            calls.append((name, args[0] if args else None))
        return _rec

    monkeypatch.setattr(import_service, "stop_worker", recorder("import"))
    monkeypatch.setattr(analysis_queue, "stop_worker", recorder("analysis"))
    monkeypatch.setattr(mdns_service, "stop_mdns", recorder("mdns"))
    monkeypatch.setattr(app_module, "checkpoint_wal", recorder("checkpoint"))

    async with await _boot(app):
        await _settled(app)

    assert [name for name, _ in calls] == ["import", "analysis", "mdns", "checkpoint"], calls
    assert calls[-1][1] is engine, "the checkpoint ran on the wrong engine"


async def test_the_real_checkpoint_truncates_this_databases_wal(app, boot_db):
    """Not a recorder this time: the actual `checkpoint_wal`, on the file.

    WAL mode is real here (the production connect hook is attached), so after
    a boot that wrote flags and a prune, the `-wal` sidecar has content — and
    a clean shutdown must fold it back into the main file. A truncated WAL
    means the next boot has nothing to replay, which is one fewer moving part
    in exactly the situation that started all of this.
    """
    engine, _ = boot_db
    wal = Path(engine.url.database + "-wal")

    async with await _boot(app):
        await _settled(app)
        assert wal.exists(), "WAL mode is not in effect; the connect hook did not attach"

    assert wal.stat().st_size == 0, f"the WAL still holds {wal.stat().st_size} bytes after shutdown"


async def test_a_failing_shutdown_step_does_not_skip_the_ones_after_it(app, monkeypatch, caplog):
    """One raising step used to skip every step after it — including the checkpoint."""
    from headroom import app as app_module
    from headroom.services import mdns_service

    ran = []

    async def boom():
        raise RuntimeError("mdns refused to stop")

    async def note(*_):
        ran.append("checkpoint")

    monkeypatch.setattr(mdns_service, "stop_mdns", boom)
    monkeypatch.setattr(app_module, "checkpoint_wal", note)
    caplog.set_level("WARNING")

    async with await _boot(app):
        await _settled(app)

    assert ran == ["checkpoint"], "the checkpoint was skipped after an earlier step raised"
    assert any("mdns refused to stop" in r.getMessage() for r in caplog.records)
