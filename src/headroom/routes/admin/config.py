"""What this deployment is actually configured to do, right now.

Every runtime toggle in this app is an environment variable read live at call
time, which is right for testing and unhelpful for the one question an
operator actually has: *is this box doing what I think it is?* Answering it
previously meant `docker inspect`, or re-reading the compose overlay you
believe you started, or guessing.

Deliberately reports EFFECTIVE values — what the code will do on the next call
— rather than what any file says. A typo'd `HEADROOM_BACKUP_KEEP=five`
silently falls back to the default, because that is `env_int`'s documented
degrade-don't-crash contract, and this endpoint is where that becomes visible
instead of being discovered a month later by a backup that never ran.

No secrets, and no key presence either: the key-status endpoints already
answer that, and restating it here would be a second place to keep the same
redaction correct.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings
from headroom.database import get_db
from headroom.limits import max_body_bytes
from headroom.schemas.admin import EffectiveConfig
from headroom.services import analysis_queue, backup_service, import_service, settings_service
from headroom.utils import disk

router = APIRouter()


@router.get("/config", response_model=EffectiveConfig)
async def effective_config(db: AsyncSession = Depends(get_db)):
    """The runtime configuration in force, as the code sees it.

    "As the code sees it" has to mean the RESOLVED value, not the environment
    default: the model reported `settings.anthropic_model` while every caller
    resolves it through `settings_service.get_anthropic_model(db)` (DB wins),
    so with a model chosen in the UI this endpoint named the wrong one — the
    opposite of its purpose. Same for the off-box upload, which counted only
    the env command and ignored a provider configured in Settings.
    """
    space = disk.check(settings.upload_dir)
    model_id, model_source = await settings_service.get_anthropic_model(db)
    try:
        upload = await backup_service.resolve_upload_argv(db, Path("/probe.tar.gz"))
        upload_configured = upload is not None
    except ValueError:
        # A stored destination that no longer validates IS configured — and
        # broken. Reporting it as absent would hide the exact thing worth seeing.
        upload_configured = True
    return {
        "workers": {
            # `expected` vs `alive` is the whole point of reporting both: they
            # differ exactly when something has died, and `alive` alone cannot
            # tell that apart from "switched off on purpose".
            "import": {
                "expected": import_service.worker_expected(),
                "alive": import_service.worker_alive(),
            },
            "analysis": {
                "expected": analysis_queue.worker_expected(),
                "alive": analysis_queue.worker_alive(),
                "queued": analysis_queue.queue_depth(),
            },
        },
        "backups": {
            "enabled": backup_service.backup_enabled(),
            "interval_hours": backup_service.backup_interval_hours(),
            # A COUNT since 2.40 — see `backup_service._enforce_retention` for
            # why age-based pruning and change-gating cannot coexist.
            "keep": backup_service.backup_keep(),
            # Whether an off-box copy is configured at all. This is the single
            # most consequential unknown on this deployment: local rolling
            # backups on the same SD card protect against corruption, not
            # against the card.
            "off_box_upload_configured": upload_configured,
        },
        "limits": {
            "max_body_bytes": max_body_bytes(),
            "disk_min_free_mb": disk.min_free_mb(),
            "disk_warn_pct": disk.warn_pct(),
        },
        "storage": {
            "upload_dir": str(settings.upload_dir),
            "free_bytes": space.free_bytes,
            "total_bytes": space.total_bytes,
            "free_pct": space.free_pct,
            "low": space.low,
        },
        "model": model_id,
        "model_source": model_source,
    }
