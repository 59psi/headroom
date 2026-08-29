"""Review and release prices frozen as "manual" by the pre-2.57.0 edit form.

Deliberately an explicit, previewable action rather than a startup backfill.
Nothing in the database records whether a `manual` stamp came from a person
typing a price or from the Edit form resending one it had seeded, and the
values are identical either way — so which are wrong is a judgment only the
owner can make. Same shape, and the same reason, as the construction audit.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.admin import FrozenPriceRow, PriceReleaseResult, SharedPriceGroup
from headroom.services import price_audit, shared_price_audit
from headroom.services.activity_service import log_activity

router = APIRouter()


def _row(entry: price_audit.FrozenPrice) -> FrozenPriceRow:
    return FrozenPriceRow(
        hat_id=entry.hat_id,
        display_id=entry.display_id,
        model_name=entry.model_name,
        resale_price=entry.resale_price,
        estimated_new_price=entry.estimated_new_price,
        was_market_priced=entry.was_market_priced,
    )


@router.get("/prices/frozen", response_model=list[FrozenPriceRow])
async def audit_frozen_prices(db: AsyncSession = Depends(get_db)):
    """Every active hat whose price is immune to future analysis."""
    return [_row(r) for r in await price_audit.audit(db)]


@router.get("/prices/shared", response_model=list[SharedPriceGroup])
async def audit_shared_prices(db: AsyncSession = Depends(get_db)):
    """Prices carried by more than a handful of hats at once.

    A source sentence covering fifty hats is not an appraisal of any one of
    them. Reports only — the owner is who knows which hat is which.
    """
    return [
        SharedPriceGroup(
            resale_price=g.resale_price,
            source=g.source,
            hat_count=g.hat_count,
            hat_ids=g.hat_ids,
            display_ids=g.display_ids,
            missing_colorway=g.missing_colorway,
        )
        for g in await shared_price_audit.audit(db)
    ]


@router.post("/prices/release", response_model=PriceReleaseResult)
async def release_frozen_prices(
    hat_ids: list[int] | None = None,
    market_priced_only: bool = False,
    dry_run: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Hand the named hats back to the live market feed.

    `dry_run` defaults to True and `hat_ids=None` means every frozen hat, so
    the destructive reading of a bare call is the one that changes nothing.
    The price VALUE is kept — only the scope and source label are cleared, so
    the number stays visible until something better replaces it.
    """
    released = await price_audit.release(
        db, hat_ids, market_priced_only=market_priced_only, dry_run=dry_run
    )
    if not dry_run and released:
        await log_activity(
            db, kind="prices.released", entity_type="system", entity_id=None,
            summary=f"{len(released)} hat price(s) released back to the market feed",
            details={"hat_ids": [r.hat_id for r in released]},
        )
        await db.commit()
    return PriceReleaseResult(
        dry_run=dry_run, released=len(released), hats=[_row(r) for r in released]
    )
