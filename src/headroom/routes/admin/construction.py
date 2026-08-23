"""Review and undo constructions that analysis guessed.

Deliberately an explicit, previewable action rather than a startup backfill:
nothing in the database records whether a construction came from a person or
from a photo, so which ones are wrong is a judgement only the owner can make.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.admin import ConstructionAuditRow, ConstructionClearResult
from headroom.services import construction_audit
from headroom.services.activity_service import log_activity

router = APIRouter()


@router.get("/constructions/audit", response_model=list[ConstructionAuditRow])
async def audit_constructions(db: AsyncSession = Depends(get_db)):
    """Every construction on record, with how many hats are priced from it."""
    rows = await construction_audit.audit(db)
    return [
        ConstructionAuditRow(
            construction=r.construction,
            hat_count=r.hat_count,
            priced_from_table=r.priced_from_table,
        )
        for r in rows
    ]


@router.post("/constructions/clear", response_model=ConstructionClearResult)
async def clear_construction(
    value: str,
    dry_run: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Clear one construction value from every active hat carrying it.

    `dry_run=true` (the default) reports what would change and writes nothing —
    this removes data that cannot be recomputed, so the destructive form has to
    be asked for.
    """
    report = await construction_audit.clear_construction(db, value, dry_run=dry_run)

    if not dry_run and report.hats_cleared:
        await log_activity(
            db,
            kind="construction.cleared",
            entity_type="system",
            entity_id=None,
            summary=f"Cleared construction {value!r} from {report.hats_cleared} hat(s)",
            details=(
                f"model names corrected: {report.model_names_corrected}; "
                f"table prices cleared: {report.prices_cleared}; "
                f"manual prices kept: {report.manual_prices_kept}"
            ),
        )
        await db.commit()

    return ConstructionClearResult(
        construction=report.construction,
        dry_run=report.dry_run,
        hats_cleared=report.hats_cleared,
        model_names_corrected=report.model_names_corrected,
        prices_cleared=report.prices_cleared,
        manual_prices_kept=report.manual_prices_kept,
        samples=report.samples,
    )
