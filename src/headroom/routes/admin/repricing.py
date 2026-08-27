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

    Runs inline: the caller asked for it and wants the number back. A whole
    sweep paces itself between hats, so this is deliberately available even
    when the scheduler is disabled — turning the background task off should
    not remove the ability to refresh prices on purpose.

    The session factory comes off `app.state`, the seam tests swap, rather than
    from the module-level one.
    """
    repriced, considered = await repricing.reprice_once(
        session_factory=request.app.state.session_factory
    )
    repricing.health().record_success(repriced, considered)
    return RepricingRunResult(repriced=repriced, considered=considered)
