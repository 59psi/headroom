import asyncio
import logging
import os
import shutil
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from headroom import database
from headroom.auth import AuthGateMiddleware, SecurityHeadersMiddleware
from headroom.config import env_choice, env_flag, settings
from headroom.error_handler import log_unhandled, validation_error
from headroom.limits import BodySizeLimitMiddleware
from headroom.models.hat import Hat
from headroom.routes import api_router
from headroom.schemas.hat import KNOWN_CONSTRUCTIONS
from headroom.services import (
    activity_service,
    analysis_queue,
    auth_service,
    backup_service,
    ca_vault,
    hat_analysis_pipeline,
    hat_service,
    import_service,
    mdns_service,
    repricing,
    retail_pricing,
    settings_service,
    tls_health,
    vocabulary,
)
from headroom.utils import branding
from headroom.utils.paths import safe_join
from headroom.utils.redaction import redact_share_tokens

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIST = (PROJECT_ROOT / "frontend" / "dist").resolve()
SEED_BRANDING = PROJECT_ROOT / "seed" / "branding"


class _RedactShareTokens(logging.Filter):
    """Replace share tokens in any log record with a marker.

    Applied to the access logger rather than the message site, because the
    record is created inside uvicorn where this app has no call site to change.
    Mutates `record.args` when the path arrives as an argument (uvicorn's
    access log uses %-style args) and `record.msg` when it is already
    interpolated, so it catches both shapes.

    The access log is one of three sinks; `error_handler` owns the other two
    and calls `redact_share_tokens` directly. The rule itself lives in
    `utils.redaction` so the two cannot drift apart.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_share_tokens(a) if isinstance(a, str) else a
                for a in record.args
            )
        if isinstance(record.msg, str):
            record.msg = redact_share_tokens(record.msg)
        return True


def _configure_logging() -> None:
    """Apply a sane default logger config so warnings actually reach stdout.

    Only runs if the root logger has no handlers — uvicorn / pytest may have
    already configured logging, in which case we defer to them.
    """
    # These two run whether or not we own the root handler: both are about
    # other libraries' loggers, and deferring to uvicorn's config does not mean
    # inheriting its verbosity or its habit of logging our credentials.
    #
    # httpx logs the full request URL at INFO for every outbound call — the
    # marketplace, eBay, Google, Anthropic — which is noise that buries the
    # app's own lines and is the mechanism by which a secret in a URL becomes a
    # secret in a log file.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").addFilter(_RedactShareTokens())

    if logging.getLogger().handlers:
        return
    # Through `config`, the one reader of the environment: a closed set, so a
    # misspelled level is INFO plus a warning — `basicConfig(level="BOGUS")`
    # raises and the process never starts, and a typo is not worth an outage.
    # Empty (the compose passthrough's default) means INFO.
    level = env_choice(
        "HEADROOM_LOG_LEVEL", ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"), "INFO"
    )
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
        if src.stem == branding.LOGO_STEM and branding.find_logo() is not None:
            continue
        shutil.copy2(src, dest)


def _warn_if_multiprocess() -> None:
    """Headroom is single-process by design — warn loudly if run with >1 worker.

    The login rate limiter, passkey challenge store, import queue, token caches,
    and mDNS singleton are all in-memory and process-local. A second worker
    silently breaks passkey login (~50%), halves rate limiting, and can
    double-process imports into duplicate hats. Nothing shared backs them, so
    this is a hard constraint, not a tuning knob.
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


async def _merge_vocabulary_v1(db: AsyncSession) -> int:
    merged = await vocabulary.merge_case_variants(
        db, Hat.construction, known=KNOWN_CONSTRUCTIONS
    )
    return merged + await vocabulary.merge_case_variants(db, Hat.artist_series)


async def _merge_vocabulary_v2(db: AsyncSession) -> int:
    """v1's merge again, now that the key also folds punctuation — plus colorway.

    `vocabulary`'s key used to fold case and whitespace only, so an install
    that already ran v1 still holds `A-Game` beside `A Game` (and the colorway
    field, canonicalized on write since, was never merged at all). Idempotent,
    so a database v1 already fully merged changes nothing.
    """
    merged = await _merge_vocabulary_v1(db)
    return merged + await vocabulary.merge_case_variants(db, Hat.colorway)


#: The one-time data repairs, in the order they run: (flag, repair, log line).
#: Each runs once per database and is marked done in `app_settings`, so a
#: restart never repeats one — the difference between repairing a collection
#: and re-pricing or renaming it daily. One loop, where there were four
#: hand-copied `if get_setting(...) is None: ...; set_setting(...)` blocks,
#: each free to forget its own flag. The repairs are looked up on their
#: modules at CALL time (the lambdas), so a test that patches one reaches it.
_ONE_TIME_REPAIRS: tuple[tuple[str, Callable[[AsyncSession], Awaitable[int]], str], ...] = (
    # Collapse case/whitespace variants of the free-text vocabulary fields
    # ("Neon"/"NEON"/"neon" -> one collection). Canonicalization only covers
    # writes, so values that predate it, or arrived by import, need this once.
    ("vocabulary_merged_v1", lambda db: _merge_vocabulary_v1(db),
     "Merged %d case-variant vocabulary value(s)"),
    ("retail_prices_v2", lambda db: retail_pricing.backfill_retail_prices(db),
     "Re-priced %d hat(s) from the melin retail table "
     "(the old prompt anchors were years stale)"),
    ("model_names_split_v1", lambda db: hat_analysis_pipeline.backfill_split_model_names(db),
     "Split a leaked colorway out of %d model name(s) — the tool schema had no "
     "colorway field, so Claude appended it to the one field every match gates on"),
    # Normalize general_color onto the curated palette so the color filter
    # chips behave consistently.
    ("color_names_normalized_v1", lambda db: hat_service.normalize_existing_colors(db),
     "Normalized general_color on %d existing hat colors"),
    ("vocabulary_merged_v2", lambda db: _merge_vocabulary_v2(db),
     "Merged %d spelling-variant vocabulary value(s) (punctuation and colorway)"),
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    _configure_logging()
    _warn_if_multiprocess()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    # No `cases` directory: there is deliberately no case-photo feature (see
    # `tests/test_photos.py::test_there_is_no_case_photo_route`). It was still
    # being created on every boot long after the last reader was removed.
    (settings.upload_dir / "hats").mkdir(exist_ok=True)
    branding_dir = settings.upload_dir / "branding"
    branding_dir.mkdir(exist_ok=True)
    _seed_branding(branding_dir)

    # THE seam. Every session this function or the loops it starts open comes
    # from `app.state`, never from the module-level `async_session` — which is
    # the mistake `error_handler` and `reprice_once` both document: it works in
    # production and silently talks to the wrong database in every test. Until
    # this, the lifespan reached for the module global in five places and no
    # test could boot it, so the app's entire wiring — which loops start, which
    # backfills run, what seeds the health records — was the one thing the
    # suite never executed. `create_app` seeds both defaults; tests override.
    factory = app.state.session_factory
    bind = app.state.engine
    await database.init_db(bind=bind, session_factory=factory)

    async with factory() as db:
        for flag, repair, done_message in _ONE_TIME_REPAIRS:
            if await settings_service.get_setting(db, flag) is not None:
                continue
            changed = await repair(db)
            await settings_service.set_setting(db, flag, "done")
            if changed:
                logger.info(done_message, changed)
        if await auth_service.user_count(db) == 0:
            logger.warning(
                "No user accounts exist yet — open the app to create the "
                "owner account (first-run setup). All data routes require "
                "login until then."
            )
        # Every boot, not once: a re-cut the last shutdown cut short is left
        # showing its uncut original as "cutting out" forever, and only boot
        # can tell — nothing is running yet. Before the workers start, so a
        # re-cut queued after boot is never mistaken for a stranded one.
        abandoned = await hat_analysis_pipeline.abandon_interrupted_recuts(db)
        if abandoned:
            logger.info(
                "Put %d hat(s) back on their cutout — a re-cut was interrupted "
                "by the last shutdown", abandoned,
            )

    # The login verifies an unknown username against a placeholder argon2
    # hash, so a wrong name costs what a wrong password does (see
    # `auth_service.placeholder_password_hash`). That hash is computed once
    # and cached — and "once" used to mean the first failed login for an
    # unknown name, synchronously, ON the event loop: 64 MiB and up to a
    # second on a Pi with every in-flight request frozen behind it, the
    # health check included. That one attempt also paid for two argon2
    # operations where a known name pays one. Computed here instead, in a
    # worker thread under the argon2 bound, before the first request can
    # arrive, so the login only ever reads it from the cache.
    await auth_service.warm_placeholder_hash()

    logger.info("Headroom started · default-model=%s · uploads=%s",
                settings.anthropic_model, settings.upload_dir)

    # Scheduled backups — disabled in tests (no upload_dir parent at /data)
    backup_task: asyncio.Task | None = None
    if backup_service.backup_enabled():
        backup_task = asyncio.create_task(
            backup_service.scheduled_backup_loop(
                interval_hours=backup_service.backup_interval_hours(),
                keep=backup_service.backup_keep(),
                session_factory=factory,
            )
        )
    # Published so the admin API can report whether the scheduler is still
    # alive. The loop survives its own failures now, but a task can still die
    # from something outside its except clause, and "backups stopped" must be
    # answerable without reading logs.
    app.state.backup_task = backup_task

    # Periodic re-pricing. Deliberately NOT part of analysis: a marketplace
    # median keys on fields already in the database, so it needs no photo and
    # no Claude call. Coupling them is what left every appraisal frozen at the
    # date of the last bulk re-analysis, and made an expired Anthropic balance
    # stop prices as well as identification.
    app.state.repricing_task = await repricing.start_repricing(factory)

    # Bulk-import worker — single async task, drains the import queue.
    if env_flag("HEADROOM_IMPORT_WORKER_ENABLED"):
        await import_service.start_worker(factory)

    # Photo-analysis worker — drains queued single-hat uploads so the upload
    # request returns immediately. Off means the upload route runs the pipeline
    # inline (the pre-queue behavior), never silently skips it.
    if env_flag("HEADROOM_ANALYSIS_WORKER_ENABLED"):
        await analysis_queue.start_worker(factory)

    # Gallery thumbnails for hats that predate them. Off the boot path for the
    # same reason mDNS is: it is image work over every existing photo, which on
    # a Pi would visibly delay the app becoming reachable. Idempotent, so a
    # restart mid-run resumes rather than repeating.
    async def _backfill_thumbs():
        try:
            async with factory() as db:
                made = await hat_service.backfill_thumbnails(db)
            if made:
                logger.info("Generated %d missing gallery thumbnail(s)", made)
        except Exception as exc:  # noqa: BLE001 — cosmetic; never block startup
            logger.warning("Thumbnail backfill failed: %s", exc)

    thumbs_task = asyncio.create_task(_backfill_thumbs())

    async def _backfill_exports():
        """Warm the export cache for hats that predate it.

        Runs after the thumbnail sweep for a reason: thumbnails are what every
        grid in the app renders, so they are user-visible work and go first.
        The export derivative is only needed the moment somebody downloads the
        collection — but it has to be ready BEFORE they do, because building a
        few hundred of them inside that request is what made the download look
        broken.
        """
        try:
            await thumbs_task
            async with factory() as db:
                made = await hat_service.backfill_export_images(db)
            if made:
                logger.info("Generated %d missing export image(s)", made)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — cache warming; never fatal
            logger.warning("Export image backfill failed: %s", exc)

    exports_task = asyncio.create_task(_backfill_exports())

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

        Records its outcome, which it did not until now — it was the only
        background task with no health record of any kind. It is also the only
        thing bounding those two tables, and it runs once per 24h, so a
        persistent failure was one WARNING per day into a container log while
        an SD card filled. Same operational class as a failed backup, two
        levels quieter, and nothing in the API could answer whether retention
        was still running.
        """
        while True:
            try:
                async with factory() as db:
                    removed = await activity_service.prune_activity(db)
                    removed += await auth_service.prune_expired_sessions(db)
                activity_service.retention_health.record_success(removed)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — recorded, and the loop must outlive any pass
                activity_service.retention_health.record_failure(exc)
                logger.warning("retention prune loop error: %s", exc)
            try:
                await asyncio.sleep(24 * 3600)
            except asyncio.CancelledError:
                raise

    prune_task = asyncio.create_task(_prune_loop())

    async def _tls_watch_loop():
        """Daily: is the served certificate still valid, and is the CA still ours?

        Both answers already existed and **neither had a caller that was not a
        request handler**. `tls_health.check_certificate` and
        `ca_vault.check_root` ran only when somebody opened Settings → Device,
        which is the one moment an operator is already looking. The failure
        this is for is the opposite: a certificate that quietly expired and
        served for **37 days** while every other signal stayed green.

        Seeding the root fingerprint at BOOT is the sharper half. `check_root`
        records the served root the first time it sees one and reports a
        mismatch forever after — but it was reached only by that page, so a
        root regenerated before anyone opened the card was recorded as the
        expected one and the alarm was permanently disarmed. Recording at boot
        makes the first sighting happen when the CA is whatever the last
        working deployment left, not whenever somebody happens to click.

        "Is the CA still ours" has two halves, and `check_root` answers only
        the first: the root this install HANDS OUT. Whether the chain Caddy
        SERVES leads to it is `chain_matches_ca`, and it outranks expiry here
        as it does on the card — after a CA restore Caddy can go on serving a
        leaf from the authority it minted in between, valid and covering the
        name, and every device refuses it while the root file looks perfect.

        Logs and does not enforce, for the reason `tls_health` documents: the
        certificate belongs to Caddy, so failing readiness here would
        restart-loop the app without fixing anything.
        """
        while True:
            try:
                status = await asyncio.to_thread(tls_health.check_certificate)
                # `applicable` is False on every deployment without an HTTPS
                # front door, which is most of them. Not a fault, and logging
                # it as one would train the operator to ignore this line.
                if status.applicable:
                    if status.error:
                        logger.error(
                            "TLS: could not read the certificate served for %s: %s",
                            status.host, status.error,
                        )
                    elif status.chain_matches_ca is False:
                        logger.error(
                            "TLS: the certificate served for %s was not issued by the "
                            "certificate authority this server hands out — every "
                            "device that trusts that authority refuses it. Clear "
                            "Caddy's issued certificates so it reissues them "
                            "(Settings → Trust this device has the command)",
                            status.host,
                        )
                    elif status.expired:
                        logger.error(
                            "TLS: the certificate served for %s has EXPIRED — "
                            "every browser is refusing this site", status.host,
                        )
                    elif status.needs_attention:
                        logger.error(
                            "TLS: certificate for %s expires in %.0f day(s) and "
                            "renewal has evidently stopped",
                            status.host, status.days_remaining or 0.0,
                        )
                    elif status.hostname_ok is False:
                        logger.error(
                            "TLS: the certificate served for %s does not cover that "
                            "name — a browser rejects it exactly as hard as an "
                            "expired one", status.host,
                        )
                    async with factory() as db:
                        changed, expected = await ca_vault.check_root(
                            db, status.ca_sha256
                        )
                    if changed:
                        logger.error(
                            "TLS: the local CA root CHANGED — every device that "
                            "trusted %s must install the new one", expected,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — a probe must outlive any cycle
                logger.warning("TLS watch loop error: %s", exc)
            try:
                await asyncio.sleep(24 * 3600)
            except asyncio.CancelledError:
                raise

    tls_task = asyncio.create_task(_tls_watch_loop())

    # The one-shot boot work, published so a test that boots the real lifespan
    # can await it before shutting down. Not cosmetic: canceling a task in the
    # middle of an aiosqlite call invalidates its connection, and on the test
    # suite's in-memory `StaticPool` that single connection IS the database —
    # a boot-then-exit test that did not wait saw every table vanish at exit.
    # The loops (prune, TLS) are deliberately not here; their first pass is
    # observable through the health records they write.
    app.state.boot_tasks = (thumbs_task, exports_task, mdns_task)

    try:
        yield
    finally:
        for task in (backup_task, app.state.repricing_task, prune_task,
                     mdns_task, thumbs_task, exports_task, tls_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:  # noqa: BLE001 — a dead task must not abort shutdown
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
            # LAST, deliberately: the workers above still commit as they wind
            # down, so checkpointing before them would leave exactly the writes
            # made during shutdown sitting in the WAL — the ones a power cut
            # immediately after a `compose down` would find. On the app's
            # engine — the same seam `init_db` took at boot — so a test that
            # booted against one database does not checkpoint another. The
            # order is pinned by a test that boots the real lifespan and
            # records the calls, not by one that parses this tuple's source.
            lambda: database.checkpoint_wal(bind),
        ):
            try:
                await stop()
            except Exception as exc:  # noqa: BLE001 — each stop is independent cleanup
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


#: First path segments the SPA fallback must never answer for. Everything the
#: API and the operational probes own; the SPA's own routes never start with
#: these.
_NOT_SPA_PREFIXES = frozenset({"api", "health", "uploads", "openapi.json", "docs", "redoc"})


def create_app() -> FastAPI:
    # No `/docs` or `/redoc`. FastAPI's pages load Swagger UI / ReDoc from
    # cdn.jsdelivr.net, which the CSP (`script-src 'self'`, see `auth.py`)
    # blocks by design — so behind the login they rendered a blank page, a
    # feature that looked broken rather than absent. Self-hosting their
    # bundles would mean vendoring a second front end for an operator-only
    # convenience. `/openapi.json` stays, auth-gated, for any tool that wants
    # the schema.
    app = FastAPI(title="Headroom", lifespan=lifespan, docs_url=None, redoc_url=None)

    # The auth gate resolves users through this factory; tests swap it for
    # their own in-memory database.
    app.state.session_factory = database.async_session
    app.state.engine = database.engine

    # ORDER IS LOAD-BEARING. `add_middleware` PREPENDS, so the last one added
    # is the outermost and the first to see a response on the way out.
    #
    # SecurityHeadersMiddleware must therefore be added LAST. Added first — as
    # it was — it ends up innermost, behind the auth gate, and the gate's 401
    # short-circuits before ever reaching it: an unauthenticated GET /api/hats
    # came back with exactly two headers, content-type and content-length. No
    # CSP, no nosniff, no X-Frame-Options, on precisely the responses an
    # unauthenticated caller is most likely to receive.
    # Compression for the paths nothing else compresses. Behind Caddy the
    # `encode` directive does this; on `http://<ip>:8000` (the zero-config
    # remote path) and the base compose, the 550 KB bundle went over the wire
    # uncompressed — 3.6× the bytes on the first-load path three releases
    # chased. Inside the auth gate and the security headers, so a 401 is
    # still a 401 and the headers land on the compressed response.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(AuthGateMiddleware)
    # Cross-origin access is opt-in: no `HEADROOM_CORS_ORIGINS`, no CORS
    # middleware at all. The SPA is served by this app from its own origin,
    # and in development Vite proxies `/api` and `/uploads`
    # (`frontend/vite.config.ts`), so the dev SPA is same-origin as well —
    # nothing this project ships makes a cross-origin read. A CORS policy is
    # a grant of credentialed access to another origin's pages; an entry
    # nobody needs is a grant nobody meant. An entry for the Vite dev server's
    # `http://localhost:5173` shows how: on an install opened as
    # `http://localhost:8000`, a page on :5173 is same-site, so the Lax session
    # cookie rides along and the response is readable. And installed with an
    # empty list, the middleware still answered every Origin-bearing request
    # with `Access-Control-Allow-Credentials: true` — a header that means
    # nothing without an origin and misleads anyone auditing the responses.
    if settings.cors_origins:
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

        @app.get("/{full_path:path}", response_class=FileResponse, include_in_schema=False)
        async def serve_spa(request: Request, full_path: str):
            # A typo under the API or health prefixes is a 404, not the SPA
            # shell. `GET /health/readyz` answered 200 `text/html` — so a
            # watchdog pointed at a misspelled path polled a healthy-looking
            # answer forever — and `GET /api/does-not-exist` returned the
            # app's HTML to a JSON client.
            #
            # An EMPTY first segment is refused too: `//api/hats` matches no
            # API route (Starlette does not collapse slashes) and no gate
            # prefix, so it fell through to here and answered the SPA shell
            # with a 200 — the same client getting HTML from what reads as the
            # hats endpoint. No SPA route begins with a second slash.
            first = full_path.split("/", 1)[0]
            if (full_path and not first) or first in _NOT_SPA_PREFIXES:
                raise HTTPException(status_code=404, detail="Not found")
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
