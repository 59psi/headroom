"""The bulk-import worker's durability claims, as tests rather than prose.

`import_service` documents three promises — the loop survives ANY per-item
exception, the boot sweep heals crash-stranded state, and a cancelled job is
never resurrected — and until this file existed it was the least-covered
module in the codebase at 46%, with `_process_item`, `_worker_loop` and
`_recover_on_boot` entirely unexercised. Every existing import test drives the
HTTP route, and the worker is switched off in the suite, so the machinery the
docstrings are proudest of was the machinery nothing ran.

These call the internals directly and point them at the test database, which
is the only way to reach them: the worker resolves sessions through the
module-level `async_session`, so each test swaps that for the in-memory
factory the rest of the suite uses.
"""

from __future__ import annotations

import asyncio
import io
import json

import pytest
from PIL import Image

from headroom.models.import_job import ImportJob, ImportJobItem
from headroom.services import import_service
from headroom.services.claude_analysis import AnalyzedColor, HatAnalysis

from .conftest import test_session_factory as session_factory

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _worker_uses_the_test_db(monkeypatch):
    """Point the worker's own sessions at the in-memory database.

    `_process_item` deliberately opens short sessions of its own rather than
    borrowing a request's — that is what keeps SQLite's single write lock out
    of a multi-minute pipeline — so overriding the FastAPI dependency does
    nothing for it. This is the seam.
    """
    monkeypatch.setattr(import_service, "async_session", session_factory)


@pytest.fixture
def stub_claude(monkeypatch):
    async def _key(_db):
        return "sk-ant-test", "database"

    async def _analyze(_path, _key, model=None, selected_style=None, **_kw):  # noqa: ARG001
        return HatAnalysis(
            brand="Melin", model_name="A-Game Hydro", model_confidence="high",
            style_descriptor="snapback", design_notes="fixture",
            estimated_new_price_usd=60.0,
            colors=[AnalyzedColor(name="navy", hex="#1c2541", tier="primary")],
            raw=None,
        )

    monkeypatch.setattr("headroom.services.settings_service.get_anthropic_key", _key)
    monkeypatch.setattr(
        "headroom.services.hat_analysis_pipeline.analyze_hat_image", _analyze
    )


def _jpeg(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (120, 120), (90, 40, 140))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    path.write_bytes(buf.getvalue())
    return path


async def _job(total=1, status="queued", **counters):
    async with session_factory() as db:
        job = ImportJob(total=total, status=status, defaults_json=json.dumps({}), **counters)
        db.add(job)
        await db.commit()
        return job.id


async def _item(job_id, status="queued", staged_path=None, filename="a.jpg"):
    async with session_factory() as db:
        item = ImportJobItem(
            job_id=job_id, filename=filename, status=status,
            bytes=100, staged_path=str(staged_path) if staged_path else None,
        )
        db.add(item)
        await db.commit()
        return item.id


async def _read_item(item_id):
    async with session_factory() as db:
        return await db.get(ImportJobItem, item_id)


async def _read_job(job_id):
    async with session_factory() as db:
        return await db.get(ImportJob, job_id)


# ---- _process_item ---------------------------------------------------- #


async def test_a_processed_item_becomes_a_hat(client, stub_claude, isolated_upload_dir):
    """The happy path — which nothing covered, and which did not work.

    Writing this test found that bulk import failed EVERY item. `create_hat`
    ends in `_reload_hat`, which calls `db.expire_all()`; that expires every
    object in the session, including the `ImportJobItem` loaded moments
    earlier. The next line read `item.filename`, which triggered a lazy
    refresh through synchronous attribute access — impossible on an async
    session — and raised "greenlet_spawn has not been called". The per-item
    handler caught it and recorded an error, so the feature failed completely
    while presenting as a batch of bad files.

    The fix reads what it needs into plain locals before `create_hat` runs.
    This test fails without it.
    """
    from headroom.config import settings

    job_id = await _job()
    staged = _jpeg(settings.upload_dir / ".import-staging" / "a.jpg")
    item_id = await _item(job_id, staged_path=staged)

    await import_service._process_item(item_id)

    item = await _read_item(item_id)
    assert item.status == "done"
    assert item.hat_id is not None
    assert not staged.exists(), "the staged file was not cleaned up"


async def test_a_missing_staged_file_errors_the_item_not_the_worker():
    """The commonest real failure: the file vanished between queue and run.

    It must land as an errored ITEM with the reason recorded, never as an
    exception escaping into the loop.
    """
    job_id = await _job()
    item_id = await _item(job_id, staged_path="/nonexistent/gone.jpg")

    await import_service._process_item(item_id)  # must not raise

    item = await _read_item(item_id)
    assert item.status == "error"
    assert "staged file missing" in (item.error or "")
    assert (await _read_job(job_id)).errors == 1


async def test_a_failure_still_bumps_the_counter_so_the_job_can_finish():
    """A job whose failures didn't count would poll 'running' forever."""
    job_id = await _job(total=2)
    first = await _item(job_id, staged_path="/nonexistent/one.jpg")
    second = await _item(job_id, staged_path="/nonexistent/two.jpg")

    await import_service._process_item(first)
    await import_service._process_item(second)

    job = await _read_job(job_id)
    assert job.errors == 2
    assert job.status == "done", "a job of all-failures never closed"
    assert job.finished_at is not None


async def test_an_item_of_a_cancelled_job_is_left_alone():
    job_id = await _job(status="cancelled")
    item_id = await _item(job_id, staged_path="/nonexistent/x.jpg")

    await import_service._process_item(item_id)

    assert (await _read_item(item_id)).status == "queued"


async def test_an_already_terminal_item_is_not_reprocessed():
    """The boot sweep can enqueue the same id twice; the second must no-op."""
    job_id = await _job()
    item_id = await _item(job_id, status="done")

    await import_service._process_item(item_id)

    assert (await _read_item(item_id)).status == "done"
    assert (await _read_job(job_id)).done == 0  # no counter double-bump


# ---- _bump_job_counter ------------------------------------------------ #


async def test_the_error_counter_name_skew_is_handled():
    """The item status is `error` and the column is `errors`.

    `_JOB_COUNTER` exists precisely because those two names differ, which is
    the slip a bare string parameter invites.
    """
    job_id = await _job(total=3)

    await import_service._bump_job_counter(job_id, "error")
    await import_service._bump_job_counter(job_id, "done")
    await import_service._bump_job_counter(job_id, "skipped")

    job = await _read_job(job_id)
    assert (job.errors, job.done, job.skipped) == (1, 1, 1)
    assert job.status == "done"


async def test_a_cancelled_job_is_never_resurrected():
    """In-flight items keep finishing after a cancel; they must not reopen it."""
    job_id = await _job(total=1, status="cancelled")

    await import_service._bump_job_counter(job_id, "done")

    assert (await _read_job(job_id)).status == "cancelled"


async def test_an_unknown_status_bumps_nothing():
    job_id = await _job(total=1)

    await import_service._bump_job_counter(job_id, "not-a-status")

    job = await _read_job(job_id)
    assert (job.done, job.errors, job.skipped) == (0, 0, 0)


# ---- _recover_on_boot ------------------------------------------------- #


async def test_items_stranded_in_processing_are_requeued():
    """A power cut on a Pi is a normal event, not an edge case.

    Without this an item caught mid-run never retries, and the job sits at
    partial progress forever with nothing to drive it.
    """
    job_id = await _job(total=1, status="running")
    item_id = await _item(job_id, status="processing")

    await import_service._recover_on_boot()

    assert (await _read_item(item_id)).status == "queued"


async def test_a_cancelled_jobs_stranded_item_is_cancelled_not_requeued():
    """Re-queuing it would restart work the owner explicitly stopped."""
    job_id = await _job(total=1, status="cancelled")
    item_id = await _item(job_id, status="processing")

    await import_service._recover_on_boot()

    assert (await _read_item(item_id)).status == "cancelled"


async def test_a_job_whose_items_are_all_terminal_is_closed():
    """Covers the all-oversize job, which has no queued item to finish it.

    Left open, the SPA polls it forever at 0% — a job that looks like it is
    still working when nothing will ever touch it again.
    """
    job_id = await _job(total=2, status="queued")
    await _item(job_id, status="error")
    await _item(job_id, status="done")

    await import_service._recover_on_boot()

    job = await _read_job(job_id)
    assert job.status == "done"
    assert job.finished_at is not None


async def test_the_boot_sweep_recomputes_counters_from_the_items():
    """Counters are the thing a crash most easily leaves wrong.

    They are incremented separately from the item write, so a process that
    died between the two leaves them disagreeing — and the progress bar reads
    from the counters.
    """
    job_id = await _job(total=3, status="running", done=0, errors=0)
    await _item(job_id, status="done")
    await _item(job_id, status="done")
    await _item(job_id, status="error")

    await import_service._recover_on_boot()

    job = await _read_job(job_id)
    assert (job.done, job.errors) == (2, 1)
    assert job.status == "done"


async def test_a_job_with_work_left_stays_open():
    job_id = await _job(total=2, status="running")
    await _item(job_id, status="done")
    await _item(job_id, status="queued")

    await import_service._recover_on_boot()

    assert (await _read_job(job_id)).status == "running"


# ---- _worker_loop ----------------------------------------------------- #


async def test_the_loop_survives_an_item_that_blows_up(monkeypatch, caplog):
    """The headline promise: one bad item must NOT kill the worker.

    If it did, every upload queued after it would sit 'pending' forever — the
    exact failure the queue exists to prevent, made permanent.
    """
    seen: list[int] = []

    async def _boom(item_id):
        seen.append(item_id)
        if item_id == 1:
            raise RuntimeError("unforeseen escape")

    monkeypatch.setattr(import_service, "_process_item", _boom)
    monkeypatch.setattr(import_service, "_queue", asyncio.Queue())
    import_service._queue.put_nowait(1)
    import_service._queue.put_nowait(2)

    task = asyncio.create_task(import_service._worker_loop())
    await import_service._queue.join()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert seen == [1, 2], "the loop stopped after the failing item"


async def test_the_loop_marks_the_queue_task_done_even_when_it_fails():
    """`task_done()` is in a `finally` for a reason.

    Miss it and `queue.join()` never returns, so a clean shutdown hangs
    forever on a queue that is actually empty.
    """
    import inspect

    source = inspect.getsource(import_service._worker_loop)
    assert "finally:" in source
    assert source.index("finally:") < source.index("task_done")


# ---- stop_worker ------------------------------------------------------ #


async def test_stopping_the_worker_clears_the_queue():
    """Matching `analysis_queue`. A queue left behind after the consumer is
    gone is what let `create_job` believe work had been accepted."""
    await import_service.start_worker()
    assert import_service.worker_alive()

    await import_service.stop_worker()

    assert import_service._queue is None
    assert not import_service.worker_alive()
