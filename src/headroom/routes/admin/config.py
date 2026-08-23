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

from fastapi import APIRouter

from headroom.config import settings
from headroom.limits import max_body_bytes
from headroom.services import analysis_queue, backup_service, import_service
from headroom.utils import disk

router = APIRouter()


@router.get("/config")
async def effective_config():
    """The runtime configuration in force, as the code sees it."""
    space = disk.check(settings.upload_dir)
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
            "off_box_upload_configured": bool(backup_service.backup_upload_cmd()),
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
        "model": settings.anthropic_model,
    }
