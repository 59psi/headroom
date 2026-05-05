# Changelog

All notable changes are documented here. This project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and adheres to
[Semantic Versioning](https://semver.org/).

## [0.6.3] — 2026-05-04 — _eBay env detection + raw error surfacing_

### Added
- **eBay env detection.** `/api/admin/ebay/creds` now returns
  `detected_env: "production" | "sandbox" | "unknown"` by inspecting the
  saved App ID for `-PRD-` or `-SBX-` (eBay's keyset format). Settings
  page renders a colored chip next to the masked App ID — green for
  production, red for sandbox, with an explicit warning banner when
  sandbox keys are saved ("These are SANDBOX keys — they will fail with
  401. Replace with a Production keyset").
- **Defensive paste handling.** PUT /api/admin/ebay/creds now strips
  surrounding quotes (`'`, `"`, `` ` ``) in addition to whitespace, in
  case the user pastes from a code block / env-var docs that included
  delimiters.

### Changed
- **eBay OAuth errors now surface eBay's actual response.** Previously
  any non-200 from the token endpoint just displayed my generic guess.
  Now we parse eBay's structured `{error, error_description}` and lead
  with that — e.g. `"eBay OAuth returned 401 (invalid_client) — client
  authentication failed"`. The "probably sandbox" hint is appended only
  for 401s, not as the only message.
- Server-side: failed OAuth responses are now logged at WARNING with
  the full status code, error code, description, and (truncated) raw
  body so `docker logs headroom` is useful for debugging.

## [0.6.2] — 2026-05-04 — _eBay diagnostics_

### Added
- **"Test connection" button** on the eBay Settings card. Probes OAuth +
  a sample Browse search end-to-end and surfaces a structured
  `{ok, stage, detail}` so the user knows whether OAuth succeeded, the
  Browse query worked, or the creds aren't configured at all.
  Backend: new `POST /api/admin/ebay/test` endpoint and
  `ebay_service.verify_creds()` that runs the full probe and reports
  which stage failed.

### Changed
- **Specific error message for sandbox-vs-production keyset mismatch.**
  When eBay returns 401 on the OAuth call (the most common failure mode —
  user pastes Sandbox keys against the production endpoint), the error
  now reads: "401 Unauthorized from eBay OAuth. Most likely your App ID
  + Cert ID are for the sandbox keyset, but Headroom calls production.
  Generate a PRODUCTION keyset at developer.ebay.com → My Account →
  Application Keysets, then re-paste both values." Previously this
  surfaced as an opaque `502 Bad Gateway`.
- Settings card help text now explicitly calls out **Production**
  (vs Sandbox) as the required keyset type.

## [0.6.1] — 2026-05-03 — _user style is ground truth + tap-to-edit colors_

### Changed
- **Owner-selected style is now ground truth for Claude.** When a hat is
  uploaded with `style=trenches`, the analysis prompt explicitly tells
  Claude that line is authoritative — Claude identifies the specific
  variant within the Trenches line (Hydro / Icon / Infinity / etc.) and
  is told NOT to pick a model from a different line. If the photo seems
  inconsistent, Claude lowers `model_confidence` rather than overriding.
  `analyze_hat_image()` gains a `selected_style` parameter; the upload
  pipeline + reanalyze route both pass `hat.style`. Fixes the case where
  a Trenches snapback was being labeled as an A-Game Hydro.

### Added
- **Tap-to-edit color rows** on the Hat detail page. Every color in the
  palette is now a button that opens a modal with: a big color preview
  that triggers the system color wheel (iOS Safari opens its native
  picker), a hex text field, specific name + general (filter) name
  fields, and a tier dropdown. Save / remove / cancel. New "+ Add Color"
  button at the top of the palette card. Backed by the existing
  `PUT /api/hats/{id}/colors` endpoint.

## [0.6.0] — 2026-05-03 — _Share-to-Headroom + version display_

### Added
- **Web Share Target API** in `manifest.json` — Android Chrome users who
  install Headroom as a PWA get a "Share to Headroom" entry in the system
  share sheet automatically. Selected photos route through the existing
  bulk-import job worker. New backend endpoint `POST /share` accepts the
  multipart payload, queues an import job, and 303-redirects into
  `/hats/import?job=N` so the SPA renders progress.
- **iOS Shortcut recipe** in Settings — step-by-step instructions for
  building a one-time Shortcut that POSTs photos from the iOS Photos
  share sheet to `/api/hats/import`. Auto-fills the URL with the running
  origin so users can copy it as-is.
- **App version in the footer.** `vite.config.ts` reads `package.json`
  and bakes the version into the bundle as `__APP_VERSION__`. Footer
  always shows the running build.
- `BulkImportPage` now reads `?job=N` from the URL so the share-target
  redirect lands on the active job.

### Bumped
- Project version → `0.6.0` (synced across `pyproject.toml` and
  `frontend/package.json`).

## [0.5.0] — 2026-05-03 — _Polish_

PWA install + photo crop on upload. Pure UX wins, no data model touches.

### Added
- **Installable PWA.** Proper `manifest.json` (192px + 512px + maskable
  icons, standalone display, theme color, background color) and
  `apple-touch-icon` link in `index.html`. Generated PNG icons from the
  seed logo via Pillow on every build. iOS "Add to Home Screen" now
  produces a fullscreen Headroom app with the brand icon.
- **Photo edit on upload** via `react-easy-crop` (~30KB gzipped, no peer
  deps). PhotoCapture flow now: pick → crop modal (free aspect, 90°
  rotate, zoom slider) → upload. Cropping happens client-side via canvas;
  backend pipeline is unchanged. Cancelling the crop modal uploads the
  original.

## [0.4.0] — 2026-05-03 — _Real Numbers_

Live eBay comparable-listings prices replace the heuristic resale guess.
Insurance-grade inventory report.

### Added
- **eBay Browse-API integration.** `services/ebay_service.py` does OAuth
  client-credentials → token cache → search by `brand + model + style`,
  returns mean / median / count of currently-listed comparable prices.
  Refreshes automatically when Claude finishes analysis (best-effort,
  never fails the upload). Per-hat refresh button on the detail page.
  New Hat columns: `ebay_avg_price`, `ebay_median_price`,
  `ebay_listing_count`, `ebay_search_url`, `ebay_checked_at`.
- **Settings UI for eBay creds** — admin-gated `app_id` + `cert_id` +
  `marketplace` (default `EBAY_US`), masked on read, env-var fallback
  via `HEADROOM_EBAY_APP_ID` / `HEADROOM_EBAY_CERT_ID`.
- **Inventory Report** — `GET /api/admin/inventory-report?include_disposed=&include_photos=`
  returns a self-contained HTML page with a print stylesheet (A4,
  page-break-inside avoid). Two-column totals tile + per-hat row with
  thumbnail, brand/model, condition, location, original retail, and
  best-available current value. Settings page button opens the report
  in a new tab; user uses browser Print → Save as PDF. Zero new heavy
  deps (vs. WeasyPrint's 200MB cairo / xhtml2pdf).
- **Hat detail Valuation card** now shows three tiles side-by-side:
  New Retail / eBay Median / Resale (manual), plus a refresh button
  and deep-link buttons to both eBay search and the existing Melin
  Recap link.

### Notes
- The free Browse-API tier is 5,000 calls/day; with caching + the rare
  brand/model identifier changes you'll be nowhere near it.
- Browse API surfaces *currently listed* items, not sold prices —
  asking prices skew higher than realized values. Marketplace Insights
  (sold prices) requires partner approval; deferred.

## [0.3.0] — 2026-05-03 — _Inventory Loop_

Hats in fast, hats tracked, hats out, all audited.

### Added
- **Activity log** — append-only `activity_log` table with `kind /
  entity_type / entity_id / summary / details(JSON)`. Hooks at every
  hat-service write path emit rows automatically. `/api/admin/activity-log`
  endpoint with filtering by `kind` and `entity_type`. Daily prune task
  (configurable retention via `HEADROOM_ACTIVITY_LOG_RETENTION_DAYS=90`).
  New "Recent Activity" card on the Settings page.
- **Sale / disposition tracking.** Five new Hat columns: `disposed_at`,
  `disposed_via` (sold/gifted/lost/trashed/trade), `disposed_price`,
  `disposed_to`, `disposed_notes`. Soft-delete only — undoable via
  `DELETE /api/hats/{id}/dispose`. Disposed hats free their case slot
  but remain in the DB (history preserved). `GET /api/hats?status=`
  defaults to `active`; `disposed` and `all` available. Hat detail
  page gets a Disposition card with a modal form for disposing +
  an "Undo — restore" action. Valuation page surfaces realized values.
- **Bulk photo import.** Multipart upload of up to 100 photos creates
  an `import_jobs` row + `import_job_items` per file, queues a single
  background asyncio worker that runs the existing pipeline one-at-a-time
  (resize → bg-remove → Claude → DB). Per-file status, hat-id link
  on completion, cancellation. Survives container restart (queued
  items re-enqueue at boot). New `/hats/import` page with drag-drop
  + per-file progress + defaults (style/size/condition/case) applied
  to every hat.

### Changed
- `_validate_capacity` skips disposed hats — sold/lost hats no longer
  count against case capacity.
- `_get_next_position` excludes disposed hats — the slot reopens.

### Tests: 81 → 93 (+12)
- `tests/test_disposition.py` — dispose + undispose + status filter +
  capacity-respecting-disposed.
- `tests/test_activity_log.py` — log emission, count endpoint, filters.
- `tests/test_import.py` — job creation, item structure, content-type
  rejection, cancellation. Worker disabled in conftest so jobs stay
  queued for assertion.

---

## [0.2.2] — 2026-05-02 — _author-question follow-ups_

Closes the action items from the 10 reviewer questions in the archaeology bundle's
`00-READ-FIRST.md`. Six questions, six fixes.

### Added
- **Configurable Claude model in Settings UI.** New `app_settings.anthropic_model`
  row, `GET/PUT/DELETE /api/settings/model`, datalist of known model ids on the
  Settings page. Resolution: DB > env > built-in default. (`anthropic_model` is
  passed all the way through `analyze_hat_image(model=…)`.)
- **In-app "Recent Analysis Errors" view** (`/api/admin/recent-errors`) listing
  the last 20 hats whose analysis failed, newest first, with thumbnail + error
  message + timestamp. Companion `/api/admin/recent-errors/count` powers a
  pulsing red badge on the Settings nav item — surfaces silent pipeline failures
  without anyone tailing `docker logs`.
- **One-click backup download** (`GET /api/admin/backup`) — streams a gzipped
  tar of `/data/{headroom.db, uploads/}` with an `attachment` content-disposition.
- **Scheduled rolling backups.** Background asyncio task writes a timestamped
  tar.gz to `/data/backups/` every 24 h (configurable: `HEADROOM_BACKUP_INTERVAL_HOURS`,
  `HEADROOM_BACKUP_RETENTION_DAYS=7`, `HEADROOM_BACKUP_ENABLED`). Cancelled
  cleanly on lifespan exit. Initial snapshot at startup so a fresh deploy isn't
  one bad sector away from total loss.
- **"Unassigned / In a Case / All" quick-chips** on the Hats page (auto-shown
  when there are unassigned hats), so case-orphaned hats are never invisible.
- **`/api/admin/*` route group** behind `require_admin` — same Bearer-token gate
  as the api-key endpoints.

### Changed
- `verify_api_key` now takes a model parameter and reports it in the success
  message (`"OK — model 'X' reachable."`) so the test button validates the
  active model+key combo rather than just the key.
- Bumped version to 0.2.2.

### Removed
- Stray dev SQLite files (`headroom.db`, `frontend/headroom.db`) — both were
  gitignored, just disk hygiene.

### Tests: 72 → 81 (+9)
- `tests/test_admin.py` — model setting CRUD + validation, recent-errors
  endpoints, backup gzip download (verifies content-type + payload size +
  attachment header), admin auth gate when token is set.

### Verified
- Live container: `/api/settings/model` GET → default → PUT → database → DELETE → default.
- Backup: GET returns valid gzip (~27 KB on a fresh DB), starts with the right
  Content-Disposition header, `file(1)` confirms gzip integrity.
- Container logs show `basicConfig` working, scheduler started, initial snapshot
  written, and the unset-token warning fires.

---

## [0.2.1] — 2026-05-02 — _post-archaeology hardening_

A focused security + reliability pass driven by a full-repo `/code-archaeology`
run. Closes the critical issues the audit surfaced and lifts the diagnosis
from "ready with conditions" toward "ready."

### Security
- **CRITICAL: Path traversal in SPA fallback handler closed.**
  `app.py:_safe_spa_path` now resolves the requested path and verifies it's
  inside `FRONTEND_DIST` before serving via `is_relative_to`. Previously
  `GET /%2e%2e/data/headroom.db` would return the SQLite database (and the
  Anthropic key inside it) to any caller. Verified against the live
  container: traversal attempts now return the 662-byte `index.html`
  fallback, not the 49KB DB. (`tests/test_security.py`)
- **Optional admin-token guard** on `/api/settings/api-key` PUT/DELETE/test
  via `HEADROOM_ADMIN_TOKEN`. Unset → endpoints stay open (single-user-LAN
  default) with a startup warning. Set → `Authorization: Bearer <token>`
  required, constant-time compare. (`src/headroom/auth.py`)

### Reliability / performance
- **Dropped the upload concurrency footgun.** `background_removal.py` no
  longer wraps `asyncio.to_thread` in a process-global `asyncio.Lock`;
  inference now runs on whatever worker threads asyncio's executor provides.
  A small `_init_lock` still guards the one-shot ONNX session creation.
- **Pillow no longer blocks the event loop.** `utils/photo.process_image_async`
  wraps the existing sync function via `asyncio.to_thread`; the hat upload
  route uses it. Concurrent uploads no longer wedge other requests.
- **Real `/health/ready` endpoint** that probes the DB (`SELECT 1`),
  upload-dir writability, and reports API-key configuration.
  `docker-compose.yml` now points the container `HEALTHCHECK` at it.
- **Default logging is now visible.** `app.py` calls `logging.basicConfig`
  on startup if no root handlers are configured, so `logger.warning` calls
  in `background_removal` and `hat_analysis_pipeline` actually reach
  `docker logs`. Level via `HEADROOM_LOG_LEVEL`.
- **Docker log rotation.** `docker-compose.yml` pins `max-size: 10m` and
  `max-file: 5` on the JSON log driver — no more silent SD-card fill from
  unbounded uvicorn access logs.
- **Function-local imports in `reanalyze_hat` removed.** Routes now have
  clean top-level imports for `analyze_hat_image`, `_apply_analysis`,
  `settings_service`. (`routes/hats.py`)

### Tests
- **+8 tests** covering the gaps the archaeology surfaced (72 total, all green):
  - `tests/test_pipeline_e2e.py` — happy-path Claude analysis with
    structured-response stub, reanalyze, and error-path coverage. The
    test the v0.2.0 release was missing.
  - `tests/test_security.py` — path-traversal regression + admin-token
    enforcement.
  - `tests/test_health.py` — readiness probe.

### Cleanup
- Removed unused `beautifulsoup4` dependency.
- Removed dead duplicate-branch in `utils/photo.py:25-28`.
- Removed vestigial `pending` from the `analysis_status` comment in `models/hat.py`
  (no code path ever wrote it).
- Clarified `anthropic_model` default with an inline comment + pointer to the
  `/api/settings/api-key/test` verification endpoint.

## [0.2.0] — 2026-05-02 — _"Outrun"_

The big one. Full UI rebuild + AI-powered hat identification.

### Added
- **Claude Vision analysis** for every uploaded hat photo. Single tool-use call
  to `claude-sonnet-4-6` returns brand, specific model name, model confidence
  (`high` / `medium` / `low`), style descriptor, design notes, primary /
  secondary / tertiary / accent colors with name + hex + tier, and an estimated
  new retail price in USD. Prompt caching enabled on the system prompt.
  (`src/headroom/services/claude_analysis.py`)
- **Background removal** via [`rembg`](https://github.com/danielgatis/rembg)
  with ONNX runtime. Hat photos save as transparent PNGs and float on the
  synthwave canvas. Default model is `u2netp` (4.7 MB) for Pi-friendliness;
  swap to `u2net` / `isnet-general-use` via `HEADROOM_REMBG_MODEL`.
  (`src/headroom/services/background_removal.py`)
- **Hat record** now stores: `brand`, `model_name`, `model_confidence`,
  `style_descriptor`, `design_notes`, `estimated_new_price`,
  `estimated_new_price_source`, `resale_price`, `resale_price_source`,
  `resale_price_url`, `resale_checked_at`, `analysis_status`, `analysis_error`,
  `analyzed_at`. `HatColor` gets a `tier` column.
- **Melin Recap deep-linking**: hats Claude identifies as Melin get a link to
  the matching filter page on melinrecap.com for live resale comparables.
  (`src/headroom/services/melin_recap.py`)
- **Settings page — Claude API key management.** Get / Set / Delete / Test
  connection endpoints; stored in DB (masked on read) with env-var fallback.
  (`src/headroom/routes/settings.py`, `tests/test_settings_api.py`)
- **`POST /api/hats/{id}/reanalyze`** — re-run Claude on an existing photo
  without re-uploading.
- **AppSetting** key/value model + table for app-level configuration.
  (`src/headroom/models/app_setting.py`)
- **Dockerfile** (multi-stage, multi-arch amd64+arm64, runs as non-root
  `headroom` user, pre-caches rembg model) and **docker-compose.yml** for
  one-command Pi deployment.
- **CHANGELOG.md** (this file) and a real **`.gitignore`**.

### Changed
- **Total frontend rebuild** — dropped Bootstrap 5 entirely. Synthwave / retro-80s
  design system: near-black canvas, neon hot-pink + cyan accents, sunset
  gradients, perspective grid background (desktop), Audiowide / Orbitron /
  Inter / JetBrains Mono typography, glow effects on primary actions, animated
  carousel with swipe gestures, glassmorphic modals + lightbox. CSS bundle
  shrunk from ~250 KB (Bootstrap) to **29 KB**.
- **Mobile / iPad first.** All layouts start single-column and progressively
  enhance. Tap targets ≥ 44 px. Bottom nav is the primary nav on portrait
  devices; top nav only renders at `lg+`. `viewport-fit=cover` and safe-area
  padding for notched devices.
- **Photo upload pipeline** is now: upload → resize/HEIC convert → background
  removal → Claude Vision → persist. Each step degrades gracefully. The
  canonical photo is the transparent PNG when bg-removal succeeds, the JPEG
  otherwise.
- **Search** now indexes brand alongside style/condition/size/colors/room.
- **Hats listing + gallery cards** show brand + model when known.
- **Hat detail page** redesigned with discrete sections: Identification (brand
  / model / confidence / Claude's design notes), Photo + Reanalyze, Valuation
  (new + resale tiles + Melin Recap CTA), Specs, Case, Color palette with
  tiered breakdown.
- **Edit Hat page** lets you override every Claude-derived field manually.
- **Database migrations** extended to add the new hat columns + `tier` on
  `hat_colors` + the new `app_settings` table. Existing DBs upgrade in place.

### Removed
- `colorthief` + `webcolors` dependencies (replaced by Claude Vision).
- `src/headroom/services/color_service.py`.
- Bootstrap CSS + JS imports from the frontend.

### Security
- Dockerfile runs as non-root user `headroom` (uid 1000) — addresses the
  semgrep finding about implicit-root containers.
- Inline-migration DDL is now fully static — no f-string interpolation into
  `text()` even for trusted column names.
- API keys are masked on read; only the prefix and last four characters are
  ever sent over the wire.

### Notes / known limitations
- The pipeline runs synchronously inside the upload request, so a hat upload
  with Claude + bg removal can take 5–15 s on a Pi. A future release may move
  this to a background queue.
- Melin Recap doesn't expose a stable JSON API and the listing page is
  client-rendered, so the resale_price field stays null and we surface a
  browse link instead of fabricating a number.

---

## [0.1.0] — 2026-02-22

Initial release. FastAPI + React SPA. Rooms / Cases / Hats domain. Local
ColorThief-based color detection. Bootstrap 5 navy/gold theme.
