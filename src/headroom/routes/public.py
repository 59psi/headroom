"""Public, unauthenticated endpoints (under the gate's /api/public/ open prefix).

Only genuinely public branding lives here — currently the site logo, so the
login/setup page can display it before anyone is authenticated. The main logo
path (/api/settings/logo) and the /uploads/branding files are auth-gated; this
is the one deliberately-public view of the logo image.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from headroom.routes._api import DomainErrorRoute
from headroom.utils import branding

router = APIRouter(prefix="/api/public", tags=["public"], route_class=DomainErrorRoute)


@router.get("/branding/logo", response_class=FileResponse)
async def public_branding_logo():
    """Serve the branding logo to anonymous callers (login page), or 404.

    The 404 is raised, not returned as a bare `Response(status_code=404)`: that
    was an empty body with no content type, the one 404 in the API that was
    not the JSON `{"detail": ...}` every client parses.
    """
    logo = branding.find_logo()
    if logo is None:
        raise HTTPException(status_code=404, detail="No logo is set")
    return FileResponse(logo, headers={"Cache-Control": "public, max-age=300"})
