"""Periodic re-pricing: is it alive, and can I run one now?

The status matters for the same reason the backup scheduler's does — a list of
prices cannot distinguish "nothing changed" from "nothing ran", and the second
is what had been happening for weeks.
"""

from fastapi import APIRouter, Request

from headroom.schemas.admin import RepricingRunResult, RepricingStatus
from headroom.services import repricing

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
