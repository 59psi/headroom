import logging
import os
import shutil
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from headroom.config import settings
from headroom.database import init_db
from headroom.routes import api_router

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIST = (PROJECT_ROOT / "frontend" / "dist").resolve()
SEED_BRANDING = PROJECT_ROOT / "seed" / "branding"


def _configure_logging() -> None:
    """Apply a sane default logger config so warnings actually reach stdout.

    Only runs if the root logger has no handlers — uvicorn / pytest may have
    already configured logging, in which case we defer to them.
    """
    if logging.getLogger().handlers:
        return
    level = os.environ.get("HEADROOM_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _seed_branding(target: Path) -> None:
    """Copy bundled default branding into the uploads volume on first boot.

    Idempotent — only copies files whose names are not already present, so a
    user-uploaded logo is never overwritten on restart.
    """
    if not SEED_BRANDING.is_dir():
        return
    target.mkdir(parents=True, exist_ok=True)
    for src in SEED_BRANDING.iterdir():
        if not src.is_file():
            continue
        dest = target / src.name
        if dest.exists():
            continue
        # Don't seed if a logo of *any* extension is already present
        if src.stem == "logo" and any(
            (target / f"logo{ext}").exists() for ext in (".png", ".jpg", ".jpeg", ".webp")
        ):
            continue
        shutil.copy2(src, dest)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    _configure_logging()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / "cases").mkdir(exist_ok=True)
    (settings.upload_dir / "hats").mkdir(exist_ok=True)
    branding_dir = settings.upload_dir / "branding"
    branding_dir.mkdir(exist_ok=True)
    _seed_branding(branding_dir)
    await init_db()
    if not settings.admin_token:
        logger.warning(
            "HEADROOM_ADMIN_TOKEN is not set — Anthropic API key endpoints "
            "are unauthenticated. Safe on a trusted LAN, dangerous if exposed."
        )
    logger.info("Headroom started · model=%s · uploads=%s",
                settings.anthropic_model, settings.upload_dir)
    yield


def _safe_spa_path(full_path: str) -> Path | None:
    """Resolve a SPA-fallback request and return a path inside FRONTEND_DIST or None.

    Defends against path traversal: an attacker requesting `/%2e%2e/data/headroom.db`
    must NOT escape the static frontend bundle. Resolve the candidate, then verify
    it's within the frontend root before serving.
    """
    try:
        candidate = (FRONTEND_DIST / full_path).resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    if candidate != FRONTEND_DIST and not candidate.is_relative_to(FRONTEND_DIST):
        return None
    return candidate


def create_app() -> FastAPI:
    app = FastAPI(title="Headroom", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    if settings.upload_dir.exists():
        app.mount(
            "/uploads",
            StaticFiles(directory=str(settings.upload_dir)),
            name="uploads",
        )

    if FRONTEND_DIST.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=str(FRONTEND_DIST / "assets")),
            name="frontend-assets",
        )

        @app.get("/{full_path:path}")
        async def serve_spa(request: Request, full_path: str):
            # Confine the lookup to the frontend bundle — see _safe_spa_path docstring.
            safe = _safe_spa_path(full_path)
            if safe is not None and safe.is_file():
                return FileResponse(safe)
            # SPA fallback: hand back index.html for client-side routing.
            index = FRONTEND_DIST / "index.html"
            if not index.is_file():
                raise HTTPException(status_code=404, detail="Frontend not built")
            return FileResponse(index)

    return app


app = create_app()
