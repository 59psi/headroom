"""The lifespan, booted for real, against the test database.

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

Each test here boots through `app.router.lifespan_context` and asserts an
outcome: a record that was written, a task that exists or does not, a file
that appeared, a call that happened in an order. The retention prune is the
sharpest case — its health record shipped in 2.77.0 with the loop, the route
and the card, and none of the three had a test that reached them.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select

from headroom.config import settings
from headroom.models.app_setting import AppSetting
from headroom.services import activity_service, analysis_queue, import_service, repricing
from headroom.services.task_health import TaskHealth

from tests.conftest import test_engine as engine_under_test
from tests.conftest import test_session_factory as session_factory

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


@pytest.fixture(autouse=True)
def _fresh_process_state():
    """Module-level records the lifespan writes into, reset around each boot.

    They are process-local by design (see `RepricingHealth`); a test that
    booted once and left `last_success_at` set would make the next boot's
    assertion pass without the loop having run.
    """
    activity_service.retention_health = TaskHealth(name="retention prune")
    repricing._health = repricing.RepricingHealth()
    repricing.release_full_sweep()
    yield
    activity_service.retention_health = TaskHealth(name="retention prune")
    repricing._health = repricing.RepricingHealth()
    repricing.release_full_sweep()


async def _boot(app):
    """The real thing — not a fixture, so a test can boot twice."""
    return app.router.lifespan_context(app)


async def _flags(db):
    rows = (await db.execute(
        select(AppSetting).where(AppSetting.key.in_(ONE_TIME_FLAGS))
    )).scalars().all()
    return {r.key: r.value for r in rows}


async def _settled(app):
    """Wait for boot-time database work to finish before shutting down.

    Cancelling a task mid-aiosqlite-call invalidates its connection, and the
    suite's in-memory `StaticPool` has exactly one — so a boot that is shut
    down while the first prune is still running loses every table. That is an
    artifact of the test database (a file reconnects), but a test that exits
    at once is also not a realistic shutdown: on the real box the first prune
    pass is part of boot. The one-shot tasks are awaited by handle; the prune
    is awaited through the record it writes, which is the only thing its
    infinite loop exposes.
    """
    await asyncio.gather(*app.state.boot_tasks)
    await _wait_for(
        lambda: activity_service.retention_health.last_attempt_at is not None,
        what="the boot-time retention prune",
    )


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


# --------------------------------------------------------------------------
# boot and shutdown
# --------------------------------------------------------------------------


async def test_the_lifespan_boots_against_the_test_database_and_leaves_no_task_behind(app):
    """Enter, exit, and account for every task.

    A loop that survives shutdown keeps a session factory alive and, on the
    real box, keeps writing after `compose down` has decided it is safe to
    stop — the WAL-checkpoint ordering below exists for exactly that window.
    """
    before = set(asyncio.all_tasks())

    async with await _boot(app):
        started = set(asyncio.all_tasks()) - before
        assert started, "boot started no background work at all"
        assert set(app.state.boot_tasks) <= started
        await _settled(app)

    for task in started:
        assert task.done(), f"background task survived shutdown: {task.get_name()}"

    # And the database it booted against is the test one: `init_db` ran here.
    async with session_factory() as db:
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


async def test_boot_stamps_every_one_time_backfill_and_does_not_repeat_them(app, monkeypatch):
    """Four repairs, each guarded by a flag, each run exactly once.

    The second half is the one that matters on the real box: a repair that
    re-ran on every boot would re-price or rename the collection daily. The
    color normalizer is the probe because it is the cheapest to count; the
    property is the flags, which cover all four.
    """
    from headroom.services import hat_service

    calls = []
    real = hat_service.normalize_existing_colors

    async def counting(db):
        calls.append(1)
        return await real(db)

    monkeypatch.setattr(hat_service, "normalize_existing_colors", counting)

    async with await _boot(app):
        await _settled(app)
    async with session_factory() as db:
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
    forwarded, the first sweep finds the test database's zero hats and records
    a success. Without it, the module engine points at an unopenable path
    under test and the sweep records a failure instead — so the assertion
    below cannot pass by accident.
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
        assert health.last_considered == 0, "the test database holds no hats"

    assert task.done(), "the scheduler outlived shutdown"


# --------------------------------------------------------------------------
# shutdown order
# --------------------------------------------------------------------------


async def test_shutdown_stops_workers_then_checkpoints_the_wal_last(app, monkeypatch):
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
    assert calls[-1][1] is engine_under_test, "the checkpoint ran on the wrong engine"


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
