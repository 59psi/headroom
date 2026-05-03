# Changelog

All notable changes are documented here. This project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and adheres to
[Semantic Versioning](https://semver.org/).

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
