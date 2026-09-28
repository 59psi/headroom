"""eBay credential management + comparable-listings refresh."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.routes._api import DomainErrorRoute
from headroom.schemas.admin import EbayCredsStatus, EbayCredsUpdate, EbayTestResult

# The eBay clump's one wire declaration, which `HatRead` inherits too.
from headroom.schemas.hat import EbayComps
from headroom.services import activity_service, ebay_service, hat_service, settings_service

router = APIRouter(route_class=DomainErrorRoute)


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


async def _creds_status(db: AsyncSession) -> EbayCredsStatus:
    """What is stored, as every route reports it — one derivation of `configured`.

    The PUT used to answer `configured=True` whatever it had just stored, so a
    save that produced unusable credentials reported success in the same
    breath; now the answer is read back, the way the GET reads it.
    """
    app_id, cert_id, marketplace = await ebay_service.get_creds(db)
    return EbayCredsStatus(
        configured=bool(app_id and cert_id),
        app_id_masked=settings_service.mask_key(app_id) if app_id else None,
        marketplace=marketplace,
        detected_env=_detect_ebay_env(app_id),
    )


@router.get("/ebay/creds", response_model=EbayCredsStatus)
async def get_ebay_creds(db: AsyncSession = Depends(get_db)):
    return await _creds_status(db)


@router.put("/ebay/creds", response_model=EbayCredsStatus)
async def set_ebay_creds(data: EbayCredsUpdate, db: AsyncSession = Depends(get_db)):
    # Normalization (whitespace, pasted quotes, marketplace spelling) happens
    # in `EbayCredsUpdate`, before the length checks — see `_unwrap_pasted`.
    await settings_service.set_setting(db, ebay_service.EBAY_APP_ID_KEY, data.app_id)
    await settings_service.set_setting(db, ebay_service.EBAY_CERT_ID_KEY, data.cert_id)
    await settings_service.set_setting(
        db, ebay_service.EBAY_MARKETPLACE_KEY, data.marketplace.value
    )
    await activity_service.log_activity(
        db, kind="settings.ebay_set", entity_type="system", entity_id=None,
        summary="eBay API credentials set/updated",
    )
    await db.commit()
    return await _creds_status(db)


@router.delete("/ebay/creds", status_code=204)
async def delete_ebay_creds(db: AsyncSession = Depends(get_db)):
    # All three, marketplace included: clearing the credentials used to leave
    # the marketplace behind, still reported by the status after "clear".
    for key in (
        ebay_service.EBAY_APP_ID_KEY,
        ebay_service.EBAY_CERT_ID_KEY,
        ebay_service.EBAY_MARKETPLACE_KEY,
    ):
        await settings_service.set_setting(db, key, None)
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
    """Refresh eBay comp prices for a single hat. Returns the stored price block."""
    try:
        hat = await hat_service.refresh_ebay_comps(db, hat_id)
    except ebay_service.EbayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # What was PERSISTED, read back off the hat — not the dict the service
    # returned, which could be echoed whether or not it was ever saved.
    return EbayComps.model_validate(hat, from_attributes=True)
