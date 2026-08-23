import asyncio
import logging
import os
import shutil
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from headroom.config import env_flag, settings
from headroom.database import async_session, init_db
from headroom.routes import api_router
from headroom.utils.paths import safe_join
from headroom.services import (
    activity_service,
    analysis_queue,
    backup_service,
    import_service,
    mdns_service,
)

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


def _warn_if_multiprocess() -> None:
    """Headroom is single-process by design — warn loudly if run with >1 worker.

    The login rate limiter, passkey challenge store, import queue, token caches,
    and mDNS singleton are all in-memory and process-local. A second worker
    silently breaks passkey login (~50%), halves rate limiting, and can
    double-process imports into duplicate hats. Nothing shared backs them, so
    this is a hard constraint, not a tuning knob
    (R8 — see docs/AUDIT-HISTORY.md).
    """
    for var in ("WEB_CONCURRENCY", "UVICORN_WORKERS", "GUNICORN_WORKERS"):
        raw = os.environ.get(var)
        try:
            if raw is not None and int(raw) > 1:
                logger.warning(
                    "%s=%s but Headroom must run as a SINGLE process — its rate "
                    "limiter, passkey challenges, import queue and mDNS are all "
                    "in-memory. Run one worker or expect broken auth/imports.",
                    var, raw,
                )
        except ValueError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    _configure_logging()
    _warn_if_multiprocess()
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
        # One-time: collapse case/whitespace variants of the free-text
        # vocabulary fields ("Neon"/"NEON"/"neon" -> one collection).
        # Canonicalisation only covers writes, so values that predate it, or
        # arrived by import, need this once.
        if await settings_service.get_setting(db, "vocabulary_merged_v1") is None:
            from headroom.models.hat import Hat
            from headroom.schemas.hat import KNOWN_CONSTRUCTIONS
            from headroom.services import vocabulary

            merged = await vocabulary.merge_case_variants(
                db, Hat.construction, known=KNOWN_CONSTRUCTIONS
            )
            merged += await vocabulary.merge_case_variants(db, Hat.artist_series)
            await settings_service.set_setting(db, "vocabulary_merged_v1", "done")
            if merged:
                logger.info("Merged %d case-variant vocabulary value(s)", merged)
        if await settings_service.get_setting(db, "retail_prices_v2") is None:
            from headroom.services import retail_pricing

            repriced = await retail_pricing.backfill_retail_prices(db)
            await settings_service.set_setting(db, "retail_prices_v2", "done")
            if repriced:
                logger.info(
                    "Re-priced %d hat(s) from the melin retail table "
                    "(the old prompt anchors were years stale)", repriced,
                )
        if await settings_service.get_setting(db, "color_names_normalized_v1") is None:
            changed = await hat_service.normalize_existing_colors(db)
            await settings_service.set_setting(db, "color_names_normalized_v1", "done")
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
                keep=backup_service.backup_keep(),
            )
        )
    # Published so the admin API can report whether the scheduler is still
    # alive. The loop survives its own failures now, but a task can still die
    # from something outside its except clause, and "backups stopped" must be
    # answerable without reading logs.
    app.state.backup_task = backup_task

    # Bulk-import worker — single async task, drains the import queue.
    if env_flag("HEADROOM_IMPORT_WORKER_ENABLED"):
        await import_service.start_worker()

    # Photo-analysis worker — drains queued single-hat uploads so the upload
    # request returns immediately. Off means the upload route runs the pipeline
    # inline (the pre-queue behaviour), never silently skips it.
    if env_flag("HEADROOM_ANALYSIS_WORKER_ENABLED"):
        await analysis_queue.start_worker()

    # Gallery thumbnails for hats that predate them. Off the boot path for the
    # same reason mDNS is: it is image work over every existing photo, which on
    # a Pi would visibly delay the app becoming reachable. Idempotent, so a
    # restart mid-run resumes rather than repeating.
    async def _backfill_thumbs():
        try:
            async with async_session() as db:
                made = await hat_service.backfill_thumbnails(db)
            if made:
                logger.info("Generated %d missing gallery thumbnail(s)", made)
        except Exception as exc:  # noqa: BLE001 — cosmetic; never block startup
            logger.warning("Thumbnail backfill failed: %s", exc)

    thumbs_task = asyncio.create_task(_backfill_thumbs())

    # mDNS LAN discovery (headroom.local) — best-effort, disabled in tests.
    # zeroconf probes for ~1s before registering; keep it off the boot path.
    mdns_task = asyncio.create_task(mdns_service.start_mdns())

    # Activity-log retention pruner — runs once per day in the background
    async def _prune_loop():
        """Daily retention sweep: activity log, then expired auth sessions.

        Prunes FIRST and sleeps after. Sleeping first meant a host that reboots
        more often than once a day — a Pi on a timer switch, or anything
        following a `docker compose up -d --build` habit — never reached the
        prune at all, so both tables grew without bound while a task sat there
        looking like it was handling it.
        """
        while True:
            try:
                async with async_session() as db:
                    await activity_service.prune_activity(db)
                    await auth_service.prune_expired_sessions(db)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("retention prune loop error: %s", exc)
            try:
                await asyncio.sleep(24 * 3600)
            except asyncio.CancelledError:
                raise

    prune_task = asyncio.create_task(_prune_loop())

    try:
        yield
    finally:
        for task in (backup_task, prune_task, mdns_task, thumbs_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:  # noqa: BLE001
                    # A task that already died holds its exception, and `await`
                    # re-raises it here. Only CancelledError used to be caught,
                    # so one dead loop (e.g. the backup loop's `_backup_dir()`
                    # mkdir failing on a read-only /data — it runs outside that
                    # loop's own try) aborted the whole shutdown: the import and
                    # analysis workers were never stopped and mDNS never sent
                    # its goodbye packets, leaving items stuck in 'processing'
                    # and the hostname advertised until it timed out.
                    logger.warning("Background task %r failed: %s", task.get_name(), exc)
        # Deliberately individually guarded: each stop is independent cleanup,
        # and one raising must not skip the others.
        for stop in (
            import_service.stop_worker,
            analysis_queue.stop_worker,
            mdns_service.stop_mdns,
        ):
            try:
                await stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Shutdown step %s failed: %s", stop.__qualname__, exc)


def _safe_spa_path(full_path: str) -> Path | None:
    """Resolve a SPA-fallback request to a path inside FRONTEND_DIST, or None.

    Defends against path traversal: an attacker requesting
    `/%2e%2e/data/headroom.db` must NOT escape the static frontend bundle.
    Thin wrapper over `utils.paths.safe_join`, which is the single definition
    of that check — the share-photo streamer used to carry a second copy, and
    two correct copies of a security check are two places to keep correct.
    """
    return safe_join(FRONTEND_DIST, full_path)


def create_app() -> FastAPI:
    from headroom.auth import AuthGateMiddleware, SecurityHeadersMiddleware
    from headroom.error_handler import log_unhandled, validation_error
    from headroom.limits import BodySizeLimitMiddleware

    app = FastAPI(title="Headroom", lifespan=lifespan)

    # The auth gate resolves users through this factory; tests swap it for
    # their own in-memory database.
    app.state.session_factory = async_session

    # ORDER IS LOAD-BEARING. `add_middleware` PREPENDS, so the last one added
    # is the outermost and the first to see a response on the way out.
    #
    # SecurityHeadersMiddleware must therefore be added LAST. Added first — as
    # it was — it ends up innermost, behind the auth gate, and the gate's 401
    # short-circuits before ever reaching it: an unauthenticated GET /api/hats
    # came back with exactly two headers, content-type and content-length. No
    # CSP, no nosniff, no X-Frame-Options, on precisely the responses an
    # unauthenticated caller is most likely to receive.
    app.add_middleware(AuthGateMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)

    # Outermost of all: an oversize body should be refused before anything
    # else has spent memory on it, including the auth gate's DB lookup.
    app.add_middleware(BodySizeLimitMiddleware)

    # Every unhandled exception becomes a row in the activity log. Starlette
    # sends this handler's response and then re-raises, so the traceback still
    # reaches the container log — this adds a durable record, it does not
    # replace one.
    app.add_exception_handler(Exception, log_unhandled)

    # 422s stop echoing the value that failed validation — which on the setup
    # and login routes is a password.
    app.add_exception_handler(RequestValidationError, validation_error)

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
