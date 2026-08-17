"""Admin endpoints, split by concern.

All gated by `require_admin`, which is an alias for `require_user`: every
authenticated principal is fully privileged (single-owner model). There is no
separate admin bearer token — the retired `HEADROOM_ADMIN_TOKEN` is ignored.

Each submodule owns one area and declares a prefix-less router; the prefix,
tag and auth dependency are applied once here, so a submodule can never
accidentally ship an unguarded admin route.
"""

from fastapi import APIRouter, Depends

from headroom.auth import require_admin
from headroom.routes.admin import (
    activity,
    analysis,
    backups,
    catalog,
    ebay,
    errors,
    reports,
)

router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)

for _sub in (errors, backups, activity, reports, ebay, catalog, analysis):
    router.include_router(_sub.router)
