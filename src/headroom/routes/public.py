"""Public, unauthenticated endpoints (under the gate's /api/public/ open prefix).

Only genuinely public branding lives here — currently the site logo, so the
login/setup page can display it before anyone is authenticated. The main logo
path (/api/settings/logo) and the /uploads/branding files are auth-gated; this
is the one deliberately-public view of the logo image.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from headroom.config import settings

router = APIRouter(prefix="/api/public", tags=["public"])

_LOGO_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def _branding_logo_path():
    branding = settings.upload_dir / "branding"
    if not branding.is_dir():
        return None
    for f in sorted(branding.iterdir()):
        if f.stem == "logo" and f.suffix.lower() in _LOGO_SUFFIXES:
            return f
    return None


@router.get("/branding/logo")
async def public_branding_logo():
    """Serve the branding logo to anonymous callers (login page), or 404."""
    logo = _branding_logo_path()
    if logo is None:
        return Response(status_code=404)
    return FileResponse(logo, headers={"Cache-Control": "public, max-age=300"})
