"""Periodic re-pricing: is it alive, and can I run one now?

The status matters for the same reason the backup scheduler's does — a list of
prices cannot distinguish "nothing changed" from "nothing ran", and the second
is what had been happening for weeks.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Request

from headroom.schemas.admin import (
    RepricingRunResult,
    RepricingStatus,
    RepricingSweepStarted,
)
from headroom.services import repricing

logger = logging.getLogger(__name__)

router = APIRouter()


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
    factory = request.app.state.session_factory
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
    remaining = await repricing.count_eligible(factory)
    return RepricingRunResult(
        repriced=repriced, considered=considered, remaining=remaining
    )


@router.post("/repricing/run-all", status_code=202, response_model=RepricingSweepStarted)
async def run_repricing_all(background: BackgroundTasks, request: Request):
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

    So this answers 202 and runs uncapped in the background, exactly like the
    colorway harvest. Progress is already observable: `repricing.progress` is
    published on `GET /api/admin/repricing` and drawn by `SweepProgressBar`.

    Refuses to start a second sweep while one is in flight. `_sweep_lock` would
    serialize them safely, but queueing a second full pass behind the first is
    never what the press meant, and the card would show one bar for two runs.
    """
    if repricing.progress.snapshot()["running"]:
        return RepricingSweepStarted(started=False, already_running=True)

    # Captured here: the request's `app.state` is the seam tests swap, and the
    # background task runs after the request is gone.
    factory = request.app.state.session_factory
    background.add_task(_sweep_everything, factory)
    return RepricingSweepStarted(started=True, already_running=False)


async def _sweep_everything(session_factory) -> None:
    """The whole shelf, uncapped, off the request.

    Records the outcome for the same reason the inline route does: without it a
    sweep could fail every time while the card went on showing the last
    success. `scheduled=False` — a button press proves the code works, not that
    the background loop is alive, so it must not clear a standing failure.
    """
    try:
        repriced, considered = await repricing.reprice_once(session_factory=session_factory)
    except Exception as exc:  # noqa: BLE001 — a failed run must be RECORDED
        repricing.health().record_failure(exc)
        logger.warning("Full re-pricing sweep failed: %s", exc)
        return
    repricing.health().record_success(repriced, considered, scheduled=False)
    logger.info(
        "Full re-pricing sweep finished: %d price(s) changed across %d hat(s)",
        repriced, considered,
    )
