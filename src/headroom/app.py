import asyncio
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
from headroom.database import async_session, init_db
from headroom.routes import api_router
from headroom.services import activity_service, backup_service, import_service, mdns_service

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

    # One-time data fix: normalize general_color onto the curated palette so
    # color filter chips behave consistently (guarded by a settings flag).
    from headroom.services import auth_service, hat_service, settings_service

    async with async_session() as db:
        if await settings_service._get_setting(db, "color_names_normalized_v1") is None:
            changed = await hat_service.normalize_existing_colors(db)
            await settings_service._set_setting(db, "color_names_normalized_v1", "done")
            if changed:
                logger.info("Normalized general_color on %d existing hat colors", changed)
        if await auth_service.user_count(db) == 0:
            logger.warning(
                "No user accounts exist yet — open the app to create the "
                "owner account (first-run setup). All data routes require "
                "login until then."
            )
    logger.info("Headroom started · default-model=%s · uploads=%s",
                settings.anthropic_model, settings.upload_dir)

    # Scheduled backups — disabled in tests (no upload_dir parent at /data)
    backup_task: asyncio.Task | None = None
    if backup_service.backup_enabled():
        backup_task = asyncio.create_task(
            backup_service.scheduled_backup_loop(
                interval_hours=backup_service.backup_interval_hours(),
                retention=backup_service.backup_retention(),
            )
        )

    # Bulk-import worker — single async task, drains the import queue.
    if os.environ.get("HEADROOM_IMPORT_WORKER_ENABLED", "true").lower() in ("1", "true", "yes"):
        await import_service.start_worker()

    # mDNS LAN discovery (headroom.local) — best-effort, disabled in tests.
    await mdns_service.start_mdns()

    # Activity-log retention pruner — runs once per day in the background
    async def _prune_loop():
        while True:
            try:
                await asyncio.sleep(24 * 3600)
                async with async_session() as db:
                    await activity_service.prune_activity(db)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("activity_log prune loop error: %s", exc)

    prune_task = asyncio.create_task(_prune_loop())

    try:
        yield
    finally:
        for task in (backup_task, prune_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        await import_service.stop_worker()
        await mdns_service.stop_mdns()


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
    from headroom.auth import AuthGateMiddleware

    app = FastAPI(title="Headroom", lifespan=lifespan)

    # The auth gate resolves users through this factory; tests swap it for
    # their own in-memory database.
    app.state.session_factory = async_session

    app.add_middleware(AuthGateMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    # check_dir=False: the uploads dir is created by the lifespan (which runs
    # before the first request), not at import time. Gating the mount on the
    # directory already existing broke the seeded logo on a fresh install —
    # the SPA catch-all would serve index.html for /uploads/* until a restart.
    app.mount(
        "/uploads",
        StaticFiles(directory=str(settings.upload_dir), check_dir=False),
        name="uploads",
    )

    if FRONTEND_DIST.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=str(FRONTEND_DIST / "assets")),
            name="frontend-assets",
        )

        # Stamp index.html / manifest.json with no-cache so a fresh deploy is
        # picked up immediately. Hashed /assets/* are safe to cache as-is —
        # the filename changes on every build so stale entries are inert.
        SPA_HEADERS = {"Cache-Control": "no-cache, must-revalidate"}

        @app.get("/{full_path:path}")
        async def serve_spa(request: Request, full_path: str):
            # Confine the lookup to the frontend bundle — see _safe_spa_path docstring.
            safe = _safe_spa_path(full_path)
            if safe is not None and safe.is_file():
                return FileResponse(safe, headers=SPA_HEADERS)
            index = FRONTEND_DIST / "index.html"
            if not index.is_file():
                raise HTTPException(status_code=404, detail="Frontend not built")
            return FileResponse(index, headers=SPA_HEADERS)

    return app


app = create_app()
