"""Review and undo constructions that analysis guessed.

Deliberately an explicit, previewable action rather than a startup backfill:
nothing in the database records whether a construction came from a person or
from a photo, so which ones are wrong is a judgment only the owner can make.
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
    to: str | None = None,
    dry_run: bool = True,
    skip_owner_set: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Reassign one construction value across every active hat carrying it.

    `to` writes the right answer instead of a blank — "these are all actually
    HYDRO" is the common case, and clearing would discard a correction the
    owner already knows. Omit it to clear, which is right when the truth is
    genuinely unknown.

    `skip_owner_set` (default true) leaves alone any hat whose construction the
    audit log proves a person typed.

    `dry_run=true` (the default) reports what would change and writes nothing —
    this overwrites data that cannot be recomputed, so the destructive form has
    to be asked for.
    """
    report = await construction_audit.clear_construction(
        db, value, to=to, dry_run=dry_run, skip_owner_set=skip_owner_set
    )

    if not dry_run and report.hats_cleared:
        await log_activity(
            db,
            kind="construction.cleared",
            entity_type="system",
            entity_id=None,
            summary=(
                f"Construction {value!r} → {report.to or 'cleared'} "
                f"on {report.hats_cleared} hat(s)"
            ),
            details=(
                f"model names corrected: {report.model_names_corrected}; "
                f"table prices recomputed: {report.prices_cleared}; "
                f"manual prices kept: {report.manual_prices_kept}; "
                f"owner-set skipped: {report.owner_set_skipped}"
            ),
        )
        await db.commit()

    return ConstructionClearResult(
        construction=report.construction,
        to=report.to,
        dry_run=report.dry_run,
        hats_cleared=report.hats_cleared,
        owner_set_skipped=report.owner_set_skipped,
        model_names_corrected=report.model_names_corrected,
        prices_cleared=report.prices_cleared,
        manual_prices_kept=report.manual_prices_kept,
        samples=report.samples,
    )
