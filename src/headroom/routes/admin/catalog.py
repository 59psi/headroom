"""Colorway catalog harvesting + purchase-history import/matching."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.admin import (
    CatalogRefreshStarted,
    CatalogStatus,
    ImportPreview,
    ImportResult,
    MatchResult,
    PurchaseImport,
    PurchaseRead,
    UnclaimedFromPurchases,
    UnmatchAllResult,
    UnmatchOneResult,
)
from headroom.services import catalog_service
from headroom.services.locks import loop_lock
from headroom.services.melin_recap import MelinRecapError

logger = logging.getLogger(__name__)

router = APIRouter()

#: Strong references to in-flight harvests. asyncio keeps only a weak
#: reference to a running task, so without this the collector can take a
#: harvest mid-flight — and a harvest that vanishes never reaches the `finally`
#: that releases the claim, which is the permanent lockout `create_task` was
#: chosen to avoid in the first place.
_running_harvests: set[asyncio.Task] = set()


@router.get("/colorways/status", response_model=CatalogStatus)
async def colorway_catalog_status(db: AsyncSession = Depends(get_db)):
    """What is actually in the catalog.

    Separate from `/api/meta/colorways`, which is an autocomplete feed and caps
    at its own default limit — reading `len()` of that as "models known" made
    the card report 25 forever, which is indistinguishable from a harvest that
    genuinely found 25.
    """
    return CatalogStatus(**await catalog_service.catalog_stats(db))


@router.post("/colorways/refresh", status_code=202, response_model=CatalogRefreshStarted)
async def refresh_colorway_catalog(request: Request):
    """Harvest melinrecap listing titles into the colorway catalog.

    Runs in the background and returns immediately. The harvest is up to 9
    categories x 50 pages of sequential external calls — minutes of work — and
    doing that inside the request meant an open connection long enough for any
    reverse proxy in front of this to time out first, on the one endpoint whose
    progress you cannot see. Every other long job in this app is already
    queued; this was the exception.

    **Refuses a second harvest while one is in flight.** This had neither claim
    nor lock while `/repricing/run-all`, which is structurally the same
    endpoint, had both plus a long comment explaining why — and the asymmetry
    was acknowledged nowhere. Two concurrent harvests interleave inserts of the
    same listing title and one dies on a UNIQUE violation, which escapes the
    per-category isolation the harvest exists to provide. The card re-enables
    the moment the 202 lands, so pressing twice is ordinary behavior.

    `create_task`, not `BackgroundTasks`, for the reason `run_repricing_all`
    documents: background tasks do not run if the response fails to send, and a
    claim whose release never runs disables the endpoint for the life of the
    process.
    """
    if not catalog_service.claim_harvest():
        return CatalogRefreshStarted(
            started=False,
            already_running=True,
            detail="A catalog refresh is already running — watch its progress.",
        )
    # The app's session factory, captured from the request — the seam every
    # other background job takes. This reached for the module-level
    # `async_session`, which is the same engine in production and an
    # unopenable one under test, so the STARTED path of this endpoint could
    # never run in the suite and had no test; only the refusal branch did.
    factory = request.app.state.session_factory
    task = asyncio.create_task(_harvest_in_background(factory))
    _running_harvests.add(task)
    task.add_done_callback(_running_harvests.discard)
    return CatalogRefreshStarted()


async def _harvest_in_background(session_factory) -> None:
    """Own session: the request's is closed by the time this runs."""
    try:
        async with session_factory() as db:
            result = await catalog_service.harvest_catalog(db)
        logger.info("Colorway catalog refresh finished: %s", result)
    except MelinRecapError as exc:
        logger.warning("Colorway catalog refresh failed: %s", exc)
    except Exception:
        logger.exception("Colorway catalog refresh crashed")
    finally:
        # `finally`, not the happy path: CancelledError is a BaseException, and
        # a harvest canceled at shutdown that kept the slot would refuse every
        # press after the next start.
        catalog_service.release_harvest()


@router.post("/purchases/import", response_model=ImportPreview | ImportResult)
async def import_purchases(
    data: PurchaseImport,
    dry_run: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Store purchase line items (from order emails). Fields per item:
    item_title (required), order_ref, order_date (ISO), price, quantity, size,
    raw.

    `?dry_run=true` reports what WOULD be imported and matched and writes
    nothing. Importing runs the matcher, which mutates hats, and a bulk import
    of years of order history is exactly the case where seeing the proposed
    matches first is worth the extra round trip — there is no undo for it.
    """
    if dry_run:
        return await catalog_service.preview_import(db, data.items)
    # One import at a time. The dedupe counts rows already on record, so two
    # imports of the same file running together each saw none and wrote
    # every line twice (measured: qty 2 → 4 rows, both requests 200). The
    # matcher that follows mutates hats and is not reentrant either.
    async with loop_lock("purchase-import"):
        result = await catalog_service.import_purchases(db, data.items)
        match = await catalog_service.match_purchases_to_hats(db)
    return {**result, **match}


@router.get("/purchases", response_model=list[PurchaseRead])
async def list_purchases(db: AsyncSession = Depends(get_db)):
    return await catalog_service.list_purchases(db)


# Registered BEFORE `{purchase_id}` for the same reason `unmatch-all` is: a
# literal segment that can be read as an id is how `/api/hats/import` got
# shadowed once already.
@router.get("/purchases/unclaimed", response_model=UnclaimedFromPurchases)
async def unclaimed_from_purchases(db: AsyncSession = Depends(get_db)):
    """What re-running matching would fill in from orders already imported.

    Matching runs at the end of an import and nowhere else, so a better matcher
    or a newly analyzed `model_name` creates pairs nothing looks at again. This
    is what makes that backlog visible instead of leaving it to be guessed at.
    """
    return UnclaimedFromPurchases(**await catalog_service.unclaimed_from_purchases(db))


@router.post("/purchases/match", response_model=MatchResult)
async def rematch_purchases(
    dry_run: bool = False, db: AsyncSession = Depends(get_db)
):
    """Re-run purchase→hat matching (e.g. after adding hats or colorways).

    `?dry_run=true` returns the proposed links without writing them.
    """
    return await catalog_service.match_purchases_to_hats(db, dry_run=dry_run)


# `unmatch-all` rather than `/purchases/unmatch`, and it is registered BEFORE
# the `{purchase_id}` route: a literal segment that can be read as an id is
# how `/api/hats/import` got shadowed once already.
@router.post("/purchases/unmatch-all", response_model=UnmatchAllResult)
async def unmatch_all(db: AsyncSession = Depends(get_db)):
    """Break every purchase→hat link, reverting the fields each one set.

    The purchase rows survive — re-importing years of order history is the
    expensive part, and what was wrong is the matching, not the orders.
    Re-run `/purchases/match` afterwards to redo it.
    """
    return await catalog_service.unmatch_all_purchases(db)


@router.post("/purchases/{purchase_id}/unmatch", response_model=UnmatchOneResult)
async def unmatch_one(purchase_id: int, db: AsyncSession = Depends(get_db)):
    """Break one purchase→hat link and return the purchase to the pool.

    Reverts `purchase_price`, `purchased_at` and `colorway` on the hat, but
    only where they still hold the value this purchase wrote — anything
    edited since belongs to whoever edited it.
    """
    return await catalog_service.unmatch_purchase(db, purchase_id)
