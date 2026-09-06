"""eBay credential management + comparable-listings refresh."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.admin import EbayComps, EbayCredsStatus, EbayCredsUpdate, EbayTestResult
from headroom.services import activity_service, ebay_service, hat_service, settings_service

router = APIRouter()


def _detect_ebay_env(app_id: str | None) -> str | None:
    """eBay App IDs follow `<user>-<app>-<env>-<r1>-<r2>`. The middle env
    segment is PRD (production) or SBX (sandbox). Detecting this lets us
    flag a sandbox key paste before the user even hits Test."""
    if not app_id:
        return None
    upper = app_id.upper()
    if "-PRD-" in upper:
        return "production"
    if "-SBX-" in upper:
        return "sandbox"
    return "unknown"


def _creds_status(app_id: str | None, marketplace: str, *, configured: bool) -> EbayCredsStatus:
    return EbayCredsStatus(
        configured=configured,
        app_id_masked=settings_service.mask_key(app_id) if app_id else None,
        marketplace=marketplace,
        detected_env=_detect_ebay_env(app_id),
    )


@router.get("/ebay/creds", response_model=EbayCredsStatus)
async def get_ebay_creds(db: AsyncSession = Depends(get_db)):
    app_id, cert_id, marketplace = await ebay_service.get_creds(db)
    return _creds_status(app_id, marketplace, configured=bool(app_id and cert_id))


@router.put("/ebay/creds", response_model=EbayCredsStatus)
async def set_ebay_creds(data: EbayCredsUpdate, db: AsyncSession = Depends(get_db)):
    # Defensive normalization: strip surrounding whitespace AND any quotes
    # the user might have copied along with the value (very common when
    # pasting from a code snippet or env-var docs).
    def _clean(v: str) -> str:
        return v.strip().strip("'\"`")
    await settings_service.set_setting(db, ebay_service.EBAY_APP_ID_KEY, _clean(data.app_id))
    await settings_service.set_setting(db, ebay_service.EBAY_CERT_ID_KEY, _clean(data.cert_id))
    await settings_service.set_setting(
        db, ebay_service.EBAY_MARKETPLACE_KEY, data.marketplace.strip() or "EBAY_US"
    )
    await activity_service.log_activity(
        db, kind="settings.ebay_set", entity_type="system", entity_id=None,
        summary="eBay API credentials set/updated",
    )
    await db.commit()
    app_id, _cert, marketplace = await ebay_service.get_creds(db)
    return _creds_status(app_id, marketplace, configured=True)


@router.delete("/ebay/creds", status_code=204)
async def delete_ebay_creds(db: AsyncSession = Depends(get_db)):
    await settings_service.set_setting(db, ebay_service.EBAY_APP_ID_KEY, None)
    await settings_service.set_setting(db, ebay_service.EBAY_CERT_ID_KEY, None)
    await activity_service.log_activity(
        db, kind="settings.ebay_cleared", entity_type="system", entity_id=None,
        summary="eBay API credentials cleared",
    )
    await db.commit()


@router.post("/ebay/test", response_model=EbayTestResult)
async def test_ebay_creds(db: AsyncSession = Depends(get_db)):
    """End-to-end probe of OAuth + Browse search. Returns {ok, stage, detail}."""
    return await ebay_service.verify_creds(db)


@router.post("/ebay/refresh/{hat_id}", response_model=EbayComps)
async def refresh_ebay_for_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    """Refresh eBay comp prices for a single hat. Returns the updated price block."""
    hat = await hat_service.get_hat(db, hat_id)
    try:
        result = await ebay_service.find_comps(
            db, brand=hat.brand, model=hat.model_name, style=hat.style,
        )
    except ebay_service.EbayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    for k, v in result.items():
        setattr(hat, k, v)
    await db.commit()
    return result
