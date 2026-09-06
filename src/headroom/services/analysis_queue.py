"""Queued photo analysis, so uploading a hat returns immediately.

The upload route used to run the whole pipeline inline — rembg, then Claude,
then eBay, then Melin Recap. Every stage is individually bounded, but they add
up: Claude alone is `http_timeout` (30s) times the Anthropic SDK's default
`max_retries=2`, i.e. three attempts, and rembg on a Pi is tens of seconds
before that. A single upload could hold the request open for minutes with no
signal to the browser, which reads as a hang.

Now the route saves the photo, marks the hat `analysis_status='pending'`, and
hands the id to this queue. One worker drains it — the same single-consumer
shape as `import_service`, and for the same reason: rembg and Claude serialize
anyway, so extra workers buy nothing and multiply the failure modes.

Deliberately mirrors `import_service`'s durability rules, because the failure
modes are identical:
  * the loop survives ANY per-item exception (a bad photo must not kill it)
  * `_recover_on_boot` re-queues hats stranded in 'pending' by a crash or
    restart, so a power cut on a Pi costs a retry rather than a hat that sits
    "Analyzing…" forever
  * when no worker is running, `enqueue` reports so and the caller runs the
    pipeline inline — work is never silently dropped
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from headroom.config import env_flag
from headroom.config import settings as config_settings
from headroom.database import async_session
from headroom.models.hat import Hat
from headroom.services.hat_analysis_pipeline import finalize_hat_photo

#: The session factory this worker opens sessions with. Set by
#: `start_worker(session_factory=)` — the lifespan passes `app.state`'s — and
#: read through `_sessions()` at CALL time, so the fallback is whatever
#: `async_session` names in this module when the call happens. That last part
#: is deliberate: the existing tests redirect this module's `async_session` by
#: monkeypatch, and a factory captured at import would have silently ignored
#: them. `stop_worker()` resets it so one test's factory cannot leak into the
#: next boot.
_session_factory = None


def _sessions():
    return (_session_factory or async_session)()


logger = logging.getLogger(__name__)

# The status a hat wears between "photo saved" and "worker got to it". Any other
# analysis_status value is terminal, so this is also the exact set the boot
# sweep re-queues.
PENDING = "pending"

_queue: asyncio.Queue[int] | None = None  # holds hat IDs
_worker_task: asyncio.Task | None = None


def worker_alive() -> bool:
    """True if the background analysis worker exists and is still running."""
    return _worker_task is not None and not _worker_task.done()


def worker_expected() -> bool:
    """Whether this deployment is supposed to be running the worker at all.

    `worker_alive()` is False both for a worker that died and for one that was
    never started; readiness needs to alarm on the first and stay quiet about
    the second. See the twin in `import_service`.
    """
    return env_flag("HEADROOM_ANALYSIS_WORKER_ENABLED")


def enqueue(hat_id: int, *, cutout_only: bool = False) -> bool:
    """Queue a hat for analysis. False means nothing is draining the queue.

    A False return is the caller's cue to run the pipeline inline rather than
    drop the work — that is what keeps the feature correct when the worker is
    disabled (tests, `HEADROOM_ANALYSIS_WORKER_ENABLED=0`) or has died.
    """
    if _queue is None or not worker_alive():
        return False
    _queue.put_nowait((hat_id, cutout_only))
    return True


async def _process_hat(hat_id: int, cutout_only: bool = False) -> None:
    """Run the full pipeline for one hat in its own session."""
    async with _sessions() as db:
        hat = (await db.execute(select(Hat).where(Hat.id == hat_id))).scalar_one_or_none()
        if hat is None:
            return  # deleted between upload and analysis
        if hat.analysis_status != PENDING and not cutout_only:
            return  # already handled, or re-queued twice by the boot sweep
        if not hat.photo_path:
            hat.analysis_status = "error"
            hat.analysis_error = "Photo missing before analysis could run."
            hat.analyzed_at = datetime.now(timezone.utc)
            await db.commit()
            return

        photo_path = config_settings.upload_dir / hat.photo_path
        if not photo_path.exists():
            hat.analysis_status = "error"
            hat.analysis_error = f"Photo file missing on disk: {hat.photo_path}"
            hat.analyzed_at = datetime.now(timezone.utc)
            await db.commit()
            return

        photo_at_start = hat.photo_path
        await finalize_hat_photo(db, hat, photo_path, cutout_only=cutout_only)

        # This session has been open for minutes. If the owner replaced the
        # photo meanwhile, the upload route has already stored the new path,
        # reset the hat to 'pending' and re-queued it — so committing now would
        # write this run's stale photo_path and analysis over theirs, and the
        # re-queued run would then bail on the `!= PENDING` guard above. The new
        # photo would be orphaned on disk and never analyzed. Read the committed
        # row through a second session, because this one holds the pending write.
        if await _photo_replaced_since(hat_id, photo_at_start):
            logger.info(
                "Discarding stale analysis for hat=%s — its photo was replaced "
                "while the pipeline was running; the re-queued run will handle it.",
                hat_id,
            )
            await db.rollback()
            return

        await db.commit()


async def _photo_replaced_since(hat_id: int, photo_path: str | None) -> bool:
    """True if the hat's committed photo is no longer the one we analyzed.

    Also true when the hat was deleted mid-run, which wants the same handling:
    throw the result away.
    """
    async with _sessions() as check:
        current = (
            await check.execute(select(Hat.photo_path).where(Hat.id == hat_id))
        ).scalar_one_or_none()
    return current != photo_path


def stamp_failure(hat: Hat, exc: Exception) -> None:
    """Set the terminal error fields on a hat already loaded in a session.

    One definition of "this analysis failed", two callers: the worker (which
    owns a session of its own, below) and the routes' inline fallback (which
    already has the request's session and should not open a second connection
    just to write one row).
    """
    hat.analysis_status = "error"
    hat.analysis_error = str(exc)[:1000]
    hat.analyzed_at = datetime.now(timezone.utc)


async def mark_failed(hat_id: int, exc: Exception) -> None:
    """Record a pipeline crash on the hat, in a session of our own.

    Without this a hat that blew up mid-analysis keeps `analysis_status`
    'pending' forever, and the UI spins on it indefinitely — the exact symptom
    the queue was meant to remove.
    """
    try:
        async with _sessions() as db:
            hat = (await db.execute(select(Hat).where(Hat.id == hat_id))).scalar_one_or_none()
            if hat is not None and hat.analysis_status == PENDING:
                stamp_failure(hat, exc)
                await db.commit()
    except Exception as inner:  # noqa: BLE001 — bookkeeping must not raise
        logger.warning("Analysis error-bookkeeping failed for hat=%s: %s", hat_id, inner)


async def _worker_loop() -> None:
    """Background task: drain the analysis queue forever."""
    assert _queue is not None
    logger.info("Analysis worker started.")
    try:
        while True:
            hat_id, cutout_only = await _queue.get()
            try:
                await _process_hat(hat_id, cutout_only)
            except Exception as exc:  # one bad hat must NOT kill
                # the worker, or every later upload hangs on 'pending' forever.
                logger.exception("Analysis worker: unhandled error on hat=%s: %s", hat_id, exc)
                await mark_failed(hat_id, exc)
            finally:
                _queue.task_done()
    except asyncio.CancelledError:
        logger.info("Analysis worker canceled.")
        raise


async def _recover_on_boot() -> None:
    """Re-queue hats left 'pending' by a crash or restart."""
    assert _queue is not None
    async with _sessions() as db:
        stranded = (await db.execute(
            select(Hat.id).where(Hat.analysis_status == PENDING)
        )).scalars().all()
    for hat_id in stranded:
        # A hat stranded mid-recut by a crash gets the full run: the mode was
        # in memory and is gone, and a re-analysis is the safe over-answer.
        _queue.put_nowait((hat_id, False))
    if stranded:
        logger.info("Re-queued %d hat(s) stranded mid-analysis.", len(stranded))


async def start_worker(session_factory=None) -> None:
    """Wire up the queue + worker. Called from app.lifespan."""
    global _session_factory
    _session_factory = session_factory
    global _queue, _worker_task
    _queue = asyncio.Queue()
    _worker_task = asyncio.create_task(_worker_loop())
    await _recover_on_boot()


async def stop_worker() -> None:
    global _queue, _worker_task, _session_factory
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
    _queue = None
    # Cleared LAST. This ran first, so a worker between two awaits could open
    # one more session through the module-level fallback — the wrong database
    # under test, and the seam this module exists to respect.
    _session_factory = None


def queue_depth() -> int:
    """How many hats are waiting. Surfaced by /health/ready."""
    return _queue.qsize() if _queue is not None else 0


__all__ = [
    "PENDING",
    "enqueue",
    "start_worker",
    "stop_worker",
    "worker_alive",
    "worker_expected",
    "mark_failed",
    "stamp_failure",
    "queue_depth",
]
