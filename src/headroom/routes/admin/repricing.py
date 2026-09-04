"""Periodic re-pricing: is it alive, and can I run one now?

The status matters for the same reason the backup scheduler's does — a list of
prices cannot distinguish "nothing changed" from "nothing ran", and the second
is what had been happening for weeks.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from headroom.schemas.admin import (
    RepricingRunResult,
    RepricingStatus,
    RepricingSweepStarted,
)
from headroom.services import repricing

logger = logging.getLogger(__name__)

router = APIRouter()

#: Strong references to in-flight sweeps. `asyncio` holds only a weak reference
#: to a running task, so without this the garbage collector may collect a sweep
#: part-way through — and one that vanishes never reaches the `finally` that
#: releases the slot, which is the same permanent lockout `create_task` was
#: chosen to avoid.
_running_sweeps: set[asyncio.Task] = set()


@router.get("/repricing", response_model=RepricingStatus)
async def get_repricing():
    return RepricingStatus(**repricing.status())


@router.post("/repricing/run", response_model=RepricingRunResult)
async def run_repricing(request: Request):
    """Sweep now, rather than waiting for the next scheduled run.

    BOUNDED to `MANUAL_SWEEP_LIMIT`. The sweep runs inline because the caller
    wants the number back, and uncapped that is a multi-minute HTTP request —
    a dead spinner on a phone, then a proxy timeout, after which the result is
    thrown away and nothing is recorded. Ordering is stalest-first, so pressing
    the button again continues where this stopped; `remaining` tells the card
    whether there is more.

    Deliberately available even when the scheduler is disabled: turning the
    background task off should not remove the ability to refresh on purpose.

    The session factory comes off `app.state`, the seam tests swap, rather than
    from the module-level one.
    """
    # A full sweep holds `_sweep_lock` for minutes, so running inline here
    # would block on it — the multi-minute request, dead spinner and proxy
    # timeout this route's own cap exists to prevent. The card disables the
    # button, but a direct call must not be able to walk into it.
    if repricing.full_sweep_in_flight():
        raise HTTPException(
            status_code=409,
            detail="A full re-pricing sweep is already running — watch its progress instead.",
        )
    factory = request.app.state.session_factory
    # `remaining` means "still DUE", not "eligible at all". Without a cutoff it
    # counted every non-manual hat in the collection, so it read the same
    # before and after a run — pressing the button repeatedly reported an
    # unchanging 234, which is indistinguishable from a button that does
    # nothing.
    #
    # The horizon is the scheduler's own interval: a hat checked more recently
    # than that is current, and everything else is owed a visit. That makes the
    # number fall to zero as the shelf is worked through and grow back on its
    # own, which is the behavior "press again" advice depends on. Anchoring it
    # to the start of THIS request instead looked right and was not — hats
    # stamped by an earlier press are always older than a later request, so the
    # count stalled partway down and never reached zero.
    due_before = datetime.now(timezone.utc) - timedelta(
        hours=repricing.repricing_interval_hours()
    )
    try:
        repriced, considered = await repricing.reprice_once(
            session_factory=factory, limit=repricing.MANUAL_SWEEP_LIMIT
        )
    except Exception as exc:  # noqa: BLE001 — a failed run must be RECORDED, then raised
        # Without this a manual sweep could fail forever while the card went on
        # showing the last success, which is the same blindness the health
        # record exists to remove.
        repricing.health().record_failure(exc)
        raise
    # scheduled=False: a button press proves the code works, not that the
    # background loop is alive, so it must not clear a standing failure.
    repricing.health().record_success(repriced, considered, scheduled=False)
    remaining = await repricing.count_eligible(factory, stale_before=due_before)
    return RepricingRunResult(
        repriced=repriced, considered=considered, remaining=remaining
    )


@router.post("/repricing/run-all", status_code=202, response_model=RepricingSweepStarted)
async def run_repricing_all(request: Request):
    """Sweep the WHOLE collection, in the background.

    `/repricing/run` is bounded to `MANUAL_SWEEP_LIMIT` and that bound is
    correct for it: it runs inline because the caller wants the number back,
    and uncapped that is a multi-minute HTTP request against somebody else's
    public API — a dead spinner on a phone, then a proxy timeout, after which
    the result is discarded and nothing is recorded.

    The mistake was that blocking was the only option offered, so re-pricing
    everything meant pressing a button repeatedly or waiting for the 24h
    scheduler. Same shape as the bug `catalog_service.unclaimed_from_purchases`
    documents — a useful operation reachable only from inside a bigger one.

    So this answers 202 and runs uncapped in the background, the same shape as
    the colorway harvest (though not the same mechanism — see below). Progress
    is already observable: `repricing.progress` is published on
    `GET /api/admin/repricing` and drawn by `SweepProgressBar`.

    Refuses to start a second sweep while one is in flight. `_sweep_lock` would
    serialize them safely, but queueing a second full pass behind the first is
    never what the press meant, and the card would show one bar for two runs.

    The claim is taken SYNCHRONOUSLY here, not by reading `progress.running`.
    `progress.begin()` fires inside `reprice_once` after the lock is taken, so a
    guard on `progress` has a window where a sweep is queued but invisible, and
    two quick presses both saw False and both ran a full pass.

    **Scheduled with `create_task`, not `BackgroundTasks`, and that follows from
    holding a claim.** Starlette runs background tasks only after the response
    body has been sent; if that send fails — a phone dropping the LAN in the
    microseconds after a 202 — the task never runs. Nothing then releases the
    slot, `_full_sweep_claimed` stays true for the life of the process, and BOTH
    routes are dead: this one refuses every press and `/repricing/run` answers
    409 forever, with no way back but a restart. The colorway harvest can use a
    BackgroundTask safely precisely because it claims nothing, so a dropped task
    there costs one missed harvest. Here the guard outlives the work it guards.
    `create_task` schedules on the event loop immediately, so the release in
    `_sweep_everything`'s `finally` is reachable regardless of the response.
    """
    if not repricing.claim_full_sweep():
        return RepricingSweepStarted(started=False, already_running=True)

    # Captured here: the request's `app.state` is the seam tests swap, and the
    # task runs after the request is gone.
    factory = request.app.state.session_factory
    task = asyncio.create_task(_sweep_everything(factory))
    _running_sweeps.add(task)
    task.add_done_callback(_running_sweeps.discard)
    return RepricingSweepStarted(started=True, already_running=False)


async def _sweep_everything(session_factory) -> None:
    """The whole shelf, uncapped, off the request.

    Records the outcome for the same reason the inline route does: without it a
    sweep could fail every time while the card went on showing the last
    success. `scheduled=False` — a button press proves the code works, not that
    the background loop is alive, so it must not clear a standing failure.
    """
    # try/FINALLY: the slot must be released however this ends, or one crashed
    # sweep refuses every later press for the life of the process. `finally`
    # rather than `except Exception`, because CancelledError is a BaseException
    # — the same trap `sweep_progress` documents.
    try:
        repriced, considered = await repricing.reprice_once(session_factory=session_factory)
    except Exception as exc:  # noqa: BLE001 — a failed run must be RECORDED
        repricing.health().record_failure(exc)
        logger.warning("Full re-pricing sweep failed: %s", exc)
        return
    finally:
        repricing.release_full_sweep()
    repricing.health().record_success(repriced, considered, scheduled=False)
    logger.info(
        "Full re-pricing sweep finished: %d price(s) changed across %d hat(s)",
        repriced, considered,
    )
