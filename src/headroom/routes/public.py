"""Public, unauthenticated endpoints (under the gate's /api/public/ open prefix).

Only genuinely public branding lives here — currently the site logo, so the
login/setup page can display it before anyone is authenticated. The main logo
path (/api/settings/logo) and the /uploads/branding files are auth-gated; this
is the one deliberately-public view of the logo image.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from headroom.utils import branding

router = APIRouter(prefix="/api/public", tags=["public"])

@router.get("/branding/logo", response_class=FileResponse)
async def public_branding_logo():
    """Serve the branding logo to anonymous callers (login page), or 404."""
    logo = branding.find_logo()
    if logo is None:
        return Response(status_code=404)
    return FileResponse(logo, headers={"Cache-Control": "public, max-age=300"})
