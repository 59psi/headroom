# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

It is tracked in git (was previously local-only and drifted stale) — keep it current when you change architecture, add a service/route, or ship a release.

## Commands

- `./scripts/setup.sh` — Full setup: installs missing deps (uv, Node 20+, Docker engine sans Desktop — colima/brew on macOS, get.docker.com on Linux), syncs backend+frontend, inits DB, builds SPA. Flags: `--docker-only` (just the engine, for the compose path), `--no-docker`, `--skip-build`
- `uv run uvicorn headroom.app:app --reload` — Run backend dev server (port 8000)
- `cd frontend && npm run dev` — Run frontend dev server (port 5173, proxies to backend)
- `cd frontend && npx vite build` — Production SPA build (output: `frontend/dist`, served by backend in prod)
- `cd frontend && npx tsc -b --noEmit` — TypeScript type-check
- `uv run pytest` — Run all tests (must run from project root)
- `uv run pytest tests/test_disposition.py::test_dispose_sets_fields` — Run single test
- `docker compose up -d --build` — Run as a Docker container (Pi-friendly)
- `docker compose -f docker-compose.yml -f docker-compose.mdns.yml up -d --build` — add LAN discovery (`headroom.local:8000`; host networking, Linux/Pi)
- `docker compose -f docker-compose.yml -f docker-compose.http80.yml up -d --build` — plain HTTP on port 80 via a Caddy sidecar (`http://headroom.local`, no TLS; password login only)
- `docker compose -f docker-compose.yml -f docker-compose.https-lan.yml up -d --build` — LAN HTTPS via Caddy's internal CA, so passkeys/Face ID work on `https://headroom.local`
- `HEADROOM_DOMAIN=hats.example.com docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build` — internet-facing HTTPS (Let's Encrypt)

## Architecture

**Backend** (Python 3.12+, FastAPI, SQLAlchemy async + aiosqlite):
- `src/headroom/app.py` — App factory: lifespan (single-process guard + init_db + branding seed + scheduled-backup task + activity-log prune task + bulk-import worker + mDNS advertise), CORS, SPA serving with path-traversal protection
- `src/headroom/auth.py` — `AuthGateMiddleware` (protects all `/api/*` + `/uploads/*`; open: `/api/auth/*`, `/api/public/*`, `/health*`, SPA shell/assets; `POST /share` share-target needs auth, `GET /share/<token>` is the public share SPA page) + `require_user` dependency (`require_admin` is an alias — single role, every authenticated principal is fully privileged). Middleware resolves users via `app.state.session_factory` — tests swap it for the test DB
- `src/headroom/routes/` — `health`, `public` (unauthenticated branding logo for the login page), `auth` (setup/login/logout/me/token/passkeys), `cases`, `hats`, `import_jobs`, `rooms`, `search`, `meta`, `settings`, `admin`, `share`, `share_links` (mgmt + `/api/public/share/{token}` read-only view with token-gated photo streaming)
- `src/headroom/models/` — `ActivityLog`, `AppSetting`, `AuthSession`, `Case`, `ColorwayEntry`, `Hat`, `HatColor`, `ImportJob`, `ImportJobItem`, `PasskeyCredential`, `Purchase`, `Room`, `ShareLink`, `User`, `WearLog`
- `src/headroom/services/`
  - `claude_analysis.py` — Claude Vision tool-use call → structured `HatAnalysis`
  - `background_removal.py` — `rembg` (ONNX) → transparent PNG
  - `melin_recap.py` — Melin resale: deep links + live median asking price via the Sharetribe Flex public API (melinrecap is a Treet marketplace; anonymous public-read token, client id in config, `_query_listings` is the test seam). Degrades to link-only on API failure.
  - `catalog_service.py` — Colorway catalog harvested from melinrecap listing titles ("Model - Colorway", `parse_listing_title`); purchase-history import + hat matching (sets hat.colorway/purchase_price/purchased_at). Endpoints: POST /api/admin/colorways/refresh, /api/admin/purchases/{import,match}, GET /api/meta/colorways (autocomplete).
  - `ebay_service.py` — Browse API OAuth + comparable-listings stats. Refreshed automatically post-Claude.
  - `color_extraction.py` — Fallback dominant colors from the rembg cutout's alpha mask (hat pixels only, Pillow median-cut, curated ~25-name palette). No network. Also `normalize_hex_name()` (snap a hex to the palette) and the LAB ΔE color-similarity ranking.
  - `google_vision.py` — Fallback brand via Google Vision LOGO_DETECTION (REST + API key, no SDK). Key resolution DB > env like the others.
  - `hat_analysis_pipeline.py` — Orchestrates upload → bg-removal → Claude → eBay refresh → DB writes. `finalize_hat_photo()` (upload) and `reanalyze_existing_photo()` (reanalyze route, no bg-removal) share the key-check → Claude → apply → eBay → resale choreography; `analyze_hat_image` is patched here in tests (single seam).
  - `settings_service.py` — API-key + model + eBay-creds get/set/clear (DB > env precedence). Public `get_setting` / `set_setting` (private `_get_setting`/`_set_setting` aliases kept for back-compat).
  - `activity_service.py` — Append-only audit log; `log_activity()` is fire-and-forget. Daily retention prune.
  - `import_service.py` — Single asyncio worker draining a queue of bulk-import items. Survives restart AND per-item exceptions; boot sweep heals crash-stranded state (see Key Patterns).
  - `backup_service.py` — Streamed on-demand `tar.gz` + scheduled rolling backups to `/data/backups/`. Age-based retention (honors `_RETENTION_DAYS`), never prunes the newest, skips the startup backup when a recent one exists.
  - `mdns_service.py` — Advertises `headroom.local` on the LAN (python-zeroconf, best-effort, env-gated `HEADROOM_MDNS_*`). Registered as a background task off the boot path; Docker bridge blocks multicast so the `docker-compose.mdns.yml` overlay (host networking) is required to reach the LAN. Read-only status at `GET /api/settings/mdns`.
  - `report_service.py` — Server-side HTML inventory report (browser Print → Save as PDF).
  - `case_service.py`, `hat_service.py`, `room_service.py`, `search_service.py`, `label_service.py` (QR case-label sheet), `passkey_service.py` (WebAuthn ceremonies)
- `src/headroom/routes/share.py` — Web Share Target endpoint (`POST /share`). Receives multipart photos shared from the system share sheet (Android Chrome PWA), creates an import job, 303-redirects to `/hats/import?job=N`. iOS uses an iOS Shortcut against `/api/hats/import` instead — see Settings page recipe.
- `src/headroom/schemas/` — Pydantic I/O models (note: classes with `model_*` fields use `protected_namespaces=()` to opt out of pydantic v2's reserved namespace warning)
- `src/headroom/database.py` — Engine, async session, `init_db` with inline DDL migrations + default-room seed. SQLite `PRAGMA journal_mode=WAL` + `busy_timeout=5000` + `synchronous=NORMAL` applied on every connect (guarded to the sqlite dialect).
- `src/headroom/config.py` — pydantic-settings, env prefix `HEADROOM_`; also `env_flag(name, default=True)` for live-read runtime toggles (backup/import-worker/mDNS enable flags) that must stay monkeypatchable in tests.

**Frontend** (React 19, Vite, TypeScript, TanStack Query — _no UI framework_):
- `frontend/src/styles/tokens.css` — Synthwave palette + typography (Audiowide / Orbitron / Inter / JetBrains Mono)
- `frontend/src/styles/app.css` — All component styles + grid utilities (replaces Bootstrap)
- `frontend/src/pages/` — Page components, including `BulkImportPage`, `ValuationPage`, `LoginPage` (shows the public branding logo above the wordmark), `SettingsPage`
- `frontend/src/components/`
  - `layout/` — AppShell + TopNav + BottomNav (6 tabs: Home / Cases / Rooms / Hats / Search / Settings) + Footer (renders `v{__APP_VERSION__}` + git build SHA)
  - `common/` — Spinner, badge, swatches, lightbox, modal, empty, **DisposeModal**, **ErrorBoundary**
  - `photos/` — `PhotoCapture` (camera + file picker) + `PhotoCropper` (react-easy-crop modal)
- `frontend/src/api/` — Typed fetch clients
- `frontend/src/types/index.ts` — TS interfaces mirroring backend Pydantic schemas
- `frontend/public/icons/` — PWA icons generated at build time from `seed/branding/logo.png`
- `frontend/public/manifest.json` — Standalone PWA manifest with `share_target` (Add to Home Screen on iOS produces a fullscreen app; Android Chrome PWA gets a "Share to Headroom" share-sheet entry)
- `frontend/vite.config.ts` — Bakes `__APP_VERSION__` (from `package.json`) and `__BUILD_SHA__` (from `HEADROOM_BUILD_SHA` env / build-arg, else local git short SHA) into the bundle via Vite's `define`. Footer renders both; `vite-env.d.ts` declares the globals.

**Tests** (anyio pytest plugin, httpx AsyncClient + ASGITransport):
- `tests/` — Async tests, in-memory SQLite, conftest seeds default room, stubs out `rembg` (heavy model) AND disables backup + import-worker + mDNS via env vars
- **Auth in tests**: the `client` fixture seeds an owner (`testowner`, api_token `hr_test-api-token`) + a session row directly and presets the cookie — one argon2 hash per run, not per test. `anon_client` is unauthenticated for auth-flow tests. `app` fixture must set `app.state.session_factory = test_session_factory` or the gate middleware hits the real DB
- Tests never call the Anthropic, Google, eBay, or Sharetribe APIs; the pipeline degrades to `analysis_status='skipped'`/`'fallback'` when no key is set
- 170 passing

## Key Patterns

- **Async relationship loading**: Always use `selectinload()` for relationships; after commit + relationship changes, call `db.expire_all()` then re-query (see `_reload_hat()`, `_reload_case()`)
- **Database migrations**: `database.py:_run_migrations()` runs `ALTER TABLE` against existing DBs using **fully-static** DDL strings (no f-string interpolation into `text()`); `_HAT_COLUMN_DDL` is the source of truth for hat-column additions. `tests/test_schema_consistency.py` enforces that EVERY `Hat` model column is covered by the DDL (a forgotten entry bricks every hat read on an upgraded DB). New tables (activity_log, import_jobs, import_job_items, wear_log) are picked up by `Base.metadata.create_all`
- **SQLite tuning**: WAL + `busy_timeout` + `synchronous=NORMAL` on connect (`database.py`), so a transient `database is locked` waits rather than raising — important for the import worker + background loops on a Pi
- **Single-process by design**: rate limiter, passkey challenge store, import queue, token caches, mDNS singleton are all in-memory and process-local. `>1` worker silently breaks passkey login/rate-limiting/import dedup; the lifespan warns when `WEB_CONCURRENCY`/`UVICORN_WORKERS` > 1
- **Domain model**: Rooms contain Cases, Cases contain Hats. Cases are type-exclusive (default 4 regular hats OR 6 beanies; per-case `capacity` column overrides both). Default Room (`id=1`) cannot be deleted. Disposed hats stay in the DB but free their case slot
- **Hat photo pipeline**: Upload → Pillow resize/HEIC convert (JPEG, off the event loop) → `rembg` background removal (transparent PNG, becomes canonical) → Claude Vision tool-use → eBay refresh (best-effort) → Melin resale → persist. Per-stage timing is logged (`hat=… rembg=…s claude=…s`)
- **Pipeline degradation**: Each step (bg-removal, Claude, eBay) can fail without breaking the others; failures land in `hat.analysis_status` (`ok` / `skipped` / `error` / `fallback`) with `analysis_error` text. eBay errors are logged but never block.
- **Analysis fallback**: When Claude is unconfigured OR errors, `run_fallback_analysis()` applies mask-derived colors (PNG canonical only — background rejected by construction) plus a Google Vision logo brand when that key exists → `analysis_status='fallback'`. Produces nothing → prior `skipped`/`error` state stands. Never sets model_name/price; eBay comps stay Claude-gated.
- **Bulk import**: `import_service.start_worker()` runs from lifespan. Items processed one-at-a-time. The worker loop survives ANY per-item exception (never dies). On boot, `_recover_on_boot()` re-queues items stranded in `processing`, recomputes counters, and closes jobs whose items are all terminal (e.g. all-oversize). Cancelled jobs are never flipped back to `done`. The upload route caps per-file (chunked read) and total-batch bytes to bound RAM.
- **Activity log / audit**: `log_activity(db, kind=, entity_type=, entity_id=, summary=, details=)` is fire-and-forget; failures swallowed; **caller commits** (failed-login and other pre-exception paths must commit explicitly before raising). Covers auth events (login success/failed/blocked, password change, token rotation, passkey add/remove), backup downloads, key/cred changes, and share-link create/revoke. Daily prune task in lifespan.
- **Auth**: argon2id passwords verified/hashed OFF the event loop under a concurrency bound (`verify_password_async`/`hash_password_async`). Login rate-limited per (ip, username), in-memory, with empty-key cleanup. First-run `/api/auth/setup` is serialized against a concurrent second POST via an `app_settings` PK sentinel (no duplicate owners). **Password change rotates the API token** as well as revoking other sessions (complete compromise response)
- **API key resolution**: `settings_service.get_anthropic_key()` checks DB first (UI-managed), then env (`HEADROOM_ANTHROPIC_API_KEY`). DB always wins. Same for `get_anthropic_model()` and eBay `_get_creds()`. Set/clear via public `set_setting`/`get_setting`
- **API key safety**: Routes return only `ApiKeyStatus` (configured / source / masked prefix+suffix) — the raw key never goes back over the wire. Same for eBay creds
- **Readiness redaction**: `GET /health/ready` is unauthenticated (Docker healthcheck) — it returns booleans only for anonymous callers (no fs paths, key source, or raw error text); authenticated callers get full detail plus an import-worker liveness canary
- **Disposition (soft delete)**: `dispose_hat()` sets `disposed_at` + 4 metadata columns. `_validate_capacity` and `_get_next_position` skip disposed hats. `undispose_hat()` restores AND **reassigns `position_in_case`** so it can't collide with a hat added while it was disposed. If the case is full it lands unassigned. Default `GET /api/hats` filters to `status=active`; `?status=disposed`/`?status=all` available
- **Wear log**: one row per hat per day; unique `(hat_id, worn_at)` constraint + IntegrityError-tolerant insert make the "wearing this today" tap idempotent even under a double-tap race
- **Search**: Multi-term AND across style/condition/size/colors/room/brand/model_name; disposed hats excluded. Default searches `general_color` (normalized to the palette via `normalize_hex_name` — at analysis time, at the one-time startup backfill flagged `color_names_normalized_v1`, AND on manual `PUT /api/hats/{id}/colors` edits); `exact_colors=true` searches `color_name`
- **Color-similarity search**: `GET /api/search/color?hex=` ranks active hats by min ΔE*76 (LAB, pure-Python in `color_extraction.py`) over stored swatch hexes. Palette chips served by `GET /api/meta/colors`
- **Path traversal protection**: `_safe_spa_path()` resolves and verifies `is_relative_to(FRONTEND_DIST)` before serving — defends the SPA fallback handler against `/%2e%2e/data/headroom.db`-class attacks. The share-photo streamer applies the same `is_relative_to(upload_dir)` check
- **Query keys**: `['rooms']` for full `RoomRead[]`, `['meta', 'rooms']` for dropdown options — invalidate both on room mutations. `['settings', 'api-key']`, `['settings', 'google-vision-key']`, `['settings', 'model']`, `['settings', 'mdns']`, `['admin', 'recent-errors']`, `['admin', 'recent-errors-count']`, `['admin', 'activity']`, `['admin', 'ebay']`, `['admin', 'import-jobs']`, `['admin', 'import-job', id]`

## UI Direction

- Synthwave / retro-80s ("Outrun"). Near-black canvas, neon hot-pink + cyan accents, sunset gradients, optional perspective grid (lg+ only for perf). Long-stable HEADROOM-flicker animation (18s loop, single stutter cluster)
- **Mobile / iPad first.** Single-column layouts up; bottom nav primary (6 tabs); top nav only at `lg+`. Tap targets ≥ 44 px. iOS-zoom-prevention via 16 px input font
- **PWA-installable**: proper manifest + icons. Add to Home Screen on iOS gets a fullscreen app
- Hat photos save as transparent PNGs and float on the canvas; case photos stay as JPEGs
- All button/card styling lives in `app.css` — no Bootstrap

## Conventions

- Routes in `src/headroom/routes/`, register in `routes/__init__.py`. **Order matters** when paths overlap — `/api/hats/import` must register before `/api/hats/{hat_id}` so the path parser doesn't shadow it
- `@pytest.mark.anyio` for async tests, asyncio backend only (no trio). Sync tests in this codebase need `pytestmark = pytest.mark.anyio` because the autouse `setup_db` fixture is async. The `anyio` marker comes from the `anyio` package's pytest plugin (no separate `pytest-anyio` dependency)
- Dev dependencies in `[dependency-groups] dev` in pyproject.toml
- Frontend API functions in `frontend/src/api/`, types in `frontend/src/types/`
- `datetime.now(timezone.utc)` over the deprecated `datetime.utcnow()`
- Dockerfile must run as a non-root `USER` (semgrep-enforced); dependency install is `uv sync --frozen` only (a lock/manifest mismatch fails the build — run `uv lock` and commit)
- **Rules of Hooks**: every `useState` / `useMemo` / `useEffect` / `useQuery` must run on every render — never call hooks after an early `return`. Common bug source on pages with `if (isLoading) return <Spinner />` followed by a derived `useMemo`
- **Mobile bottom-nav layout**: `.bottom-nav` uses `display: flex` with `flex: 1 1 0` items. The `.d-lg-none` utility class **must not** force `display: initial` at mobile breakpoints — that overrides the flex and stacks tabs vertically
- **Releasing**: bump `pyproject.toml` AND `frontend/package.json` together, run `uv lock`, and add a `CHANGELOG.md` entry (Keep-a-Changelog; a **Breaking** section justifies a major bump — e.g. build-arg renames, `--frozen`, auth behavior changes). Vite bakes the package.json version into the bundle as `__APP_VERSION__`. Cut the release with a `vX.Y.Z` git tag + `gh release create` (2.0.0 onward)
- **Env vars of note**: `HEADROOM_MDNS_ENABLED`/`_HOSTNAME`/`_PORT` (LAN discovery), `HEADROOM_BUILD_SHA` (footer build stamp / Docker build-arg), `HEADROOM_BACKUP_*`, `HEADROOM_IMPORT_WORKER_ENABLED`, `HEADROOM_RP_ID`/`HEADROOM_ORIGIN` (passkeys). The retired `HEADROOM_ADMIN_TOKEN` is ignored
