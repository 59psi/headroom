# HEADROOM

> _The Outrun-grade vault for your hat collection._

![logo](seed/branding/logo.png)

Headroom is a self-hosted hat collection tracker with **AI-powered identification**.
Snap a photo and Claude Vision figures out the brand, model, dominant colors, and
estimated retail price. The background gets stripped automatically so every hat
floats on a synthwave canvas. Designed mobile/iPad-first, runs in a Docker
container on a Raspberry Pi, looks like 1986.

---

## Run it

### Docker (recommended — works on Mac, Linux, Pi)

```bash
# 1. Clone
git clone https://github.com/59psi/headroom.git && cd headroom

# 2. Install + start a Docker engine (skips itself if one is already running)
./scripts/setup.sh --docker-only

# 3. Build + run, attached so you can watch the first boot
docker compose up --build
```

Step 2 installs a complete, Docker-Desktop-free engine:
[colima](https://github.com/abiosoft/colima) + docker CLI + compose/buildx
via Homebrew on macOS, native Docker Engine via apt/dnf on Linux. If
`docker info` already works on your machine it changes nothing. **Linux:**
the script adds you to the `docker` group — log out/in (or `newgrp docker`)
before step 3.

When uvicorn reports it's listening, open http://localhost:8000 and head to
**Settings** to paste your Anthropic API key. Once it works, Ctrl-C and
relaunch it in the background:

```bash
docker compose up --build -d    # detached; follow logs with: docker compose logs -f
```

> **The first build takes a few minutes** (it pre-downloads the rembg model
> so your Pi doesn't have to); later builds are cached. Note that with `-d`
> your terminal returns immediately while the container is still building
> and booting — give it a minute before declaring it broken.

> Errors like **`unknown shorthand flag: 'd' in -d`**, **`docker: 'compose'
> is not a docker command`**, or **`Cannot connect to the Docker daemon`**
> all mean your Docker install is incomplete (missing Compose v2 plugin or
> no running engine). Step 2 fixes all of them.

To pre-bake your API key as a fallback default, edit
[`docker-compose.yml`](docker-compose.yml) and uncomment the
`HEADROOM_ANTHROPIC_API_KEY` line.

### Local (no Docker)

Prereqs: git + curl. The setup script installs everything else it needs —
uv, Python 3.12, Node 20+, backend and frontend deps.

```bash
git clone https://github.com/59psi/headroom.git && cd headroom
./scripts/setup.sh --no-docker   # drop the flag to also install a Docker engine
uv run uvicorn headroom.app:app --host 0.0.0.0 --port 8000
```

That's it — setup builds the SPA, and the backend serves it at
http://localhost:8000.

### Dev mode (hot reload)

```bash
# terminal 1 — backend (port 8000)
uv run uvicorn headroom.app:app --reload

# terminal 2 — frontend dev server (port 5173, proxies /api + /uploads to :8000)
cd frontend && npm run dev
```

---

## What's new

**v0.6 — "Share to Headroom"**: share photos straight from the system share
sheet into a bulk-import job — native share-target on Android Chrome (install
as PWA), one-time Shortcut recipe for iOS (in Settings). Recent highlights:
live eBay comparable prices + insurance-grade inventory report (v0.4), bulk
photo import, disposition tracking + activity log (v0.3), and the synthwave
rebuild with the Claude Vision analysis pipeline (v0.2).

See [CHANGELOG.md](CHANGELOG.md) for the full history.

---

## Adding hats fast

Three paths, in order of friction:

1. **One at a time** — `Hats → + New`. Crop modal pops on photo pick. ~10s per hat.
2. **Bulk** — `Hats → ⇪` (or `/hats/import`). Pick up to 100 photos at once
   from the iOS / Android Photos picker. Background worker grinds through them
   one-at-a-time. Watch progress live; tap any finished item to jump to the hat.
3. **Share sheet** — share photos from the Photos app directly into Headroom.
   Auto-creates an import job and lands you on the progress page.
   - **Android Chrome**: install Headroom as a PWA (browser menu →
     Install app). "Share to Headroom" appears in the system share sheet
     automatically. Multi-select supported.
   - **iOS Safari**: open `Settings → Share Photos to Headroom` in the app
     for the one-time Shortcut recipe. After building the Shortcut once,
     iOS Photos → Share → "Add to Headroom" works the same way.

## Configuring the AI features

The AI features need an Anthropic API key. **The DB-stored key always wins** over
the environment variable, so you can ship a docker-compose default and let users
override it from the UI.

| Source | When | Set via |
|---|---|---|
| **Database** (preferred) | Set per-user from the Settings page; persists across restarts | UI: Settings → Claude API Key |
| **Environment** (fallback) | Useful as a default for fresh installs | `HEADROOM_ANTHROPIC_API_KEY` |

### No Claude key? The fallback

Uploads never depend on Claude. Without a key (or when a Claude call fails),
a basic fallback runs instead and the hat gets `analysis_status = "fallback"`:

- **Colors — always available, no key needed.** Dominant colors are extracted
  locally from the background-removed cutout's alpha mask, so only actual hat
  pixels count — the background can't contaminate the swatches. (If background
  removal failed for a photo, no colors are guessed.)
- **Brand — optional, via Google Cloud Vision logo detection.** Create an API
  key at [console.cloud.google.com](https://console.cloud.google.com/apis/library/vision.googleapis.com)
  (enable the *Cloud Vision API*, then *Credentials → Create API key*) and
  paste it in **Settings → Google Vision Key**. Free tier is 1,000 requests
  per month — plenty for a hat collection.

Model name, price estimate, and design notes stay empty in fallback mode —
drop a Claude key in later and hit **Reanalyze** on any hat to upgrade to the
full identification. If neither fallback source produces anything, the hat
gets `analysis_status = "skipped"` exactly as before.

### What Claude actually returns

Each photo is sent in a single tool-use call against `claude-sonnet-4-6`:

```json
{
  "brand": "Melin",
  "model_name": "A-Game Hydro",
  "model_confidence": "high",
  "style_descriptor": "fitted snapback",
  "design_notes": "Classic 6-panel with embroidered icon at front and...",
  "estimated_new_price_usd": 60,
  "colors": [
    { "name": "navy", "hex": "#1c2541", "tier": "primary" },
    { "name": "white", "hex": "#f5f5f5", "tier": "secondary" }
  ]
}
```

Prompt caching is enabled on the system prompt, so repeat analyses are cheap.

### Resale prices (Melin)

When a hat is identified as Melin (by Claude or by the fallback's logo
detection), the record gets both:

- a **deep link** to the matching style filter on melinrecap.com, and
- a **live median asking price** pulled from the marketplace's public API
  (melinrecap is a Treet marketplace on Sharetribe Flex — we query the same
  anonymous, public-read listings API its own frontend uses; no scraping, no
  headless browser). Comps are narrowed to the specific model when enough
  title matches exist, otherwise the style category; the source label says
  which (e.g. "median of 83 live model listings").

If the marketplace API is unreachable, the hat degrades to link-only with a
null price — and you can always set `resale_price` manually from the Edit
Hat page. Set `HEADROOM_MELIN_CLIENT_ID` if Treet ever rotates the public
client id.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `HEADROOM_DATABASE_URL` | `sqlite+aiosqlite:///./headroom.db` | DB connection string |
| `HEADROOM_UPLOAD_DIR` | `uploads` | Where photos live on disk |
| `HEADROOM_CORS_ORIGINS` | `["http://localhost:5173"]` | Allowed CORS origins (JSON list) |
| `HEADROOM_ANTHROPIC_API_KEY` | _(unset)_ | Default API key (overridden by DB value) |
| `HEADROOM_GOOGLE_VISION_API_KEY` | _(unset)_ | Google Cloud Vision key for fallback brand (logo) detection when Claude is unavailable. DB value wins. |
| `HEADROOM_MELIN_CLIENT_ID` | _(baked in)_ | Public Sharetribe client id for melinrecap.com live resale stats. Override only if Treet rotates it. |
| `HEADROOM_ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Claude model to use for vision |
| `HEADROOM_REMBG_MODEL` | `u2netp` | rembg model name (`u2netp` is Pi-friendly; `u2net` / `isnet-general-use` are higher quality but ~170MB) |
| `HEADROOM_HTTP_TIMEOUT` | `30.0` | Outbound HTTP timeout in seconds |
| `HEADROOM_ADMIN_TOKEN` | _(unset)_ | If set, `/api/settings/api-key` and `/api/admin/*` require `Authorization: Bearer <token>`. Unset → endpoints are open (single-user-LAN default) with a startup warning. |
| `HEADROOM_LOG_LEVEL` | `INFO` | Default log level when no root handlers are configured (i.e. when running uvicorn directly). |
| `HEADROOM_BACKUP_ENABLED` | `true` | Set to `false` to disable scheduled backups (one-click download still works). |
| `HEADROOM_BACKUP_INTERVAL_HOURS` | `24` | How often the background scheduler writes a tarball to `/data/backups/`. |
| `HEADROOM_BACKUP_RETENTION_DAYS` | `7` | How many timestamped backups to keep on disk. Older ones are pruned after each new write. |
| `HEADROOM_IMPORT_WORKER_ENABLED` | `true` | Set to `false` to disable the bulk-import background worker. |
| `HEADROOM_ACTIVITY_LOG_RETENTION_DAYS` | `90` | Days of activity_log rows to keep. Pruned daily. |
| `HEADROOM_EBAY_APP_ID` | _(unset)_ | Default eBay Browse-API App ID. DB-stored value takes precedence. |
| `HEADROOM_EBAY_CERT_ID` | _(unset)_ | Default eBay Browse-API Cert ID. |

---

## Running on a Raspberry Pi

The Docker image is built as multi-arch (amd64 + arm64). On a Pi 4 / 5 running
64-bit Raspberry Pi OS or Ubuntu Server:

```bash
# Build on the Pi (slow first build, fine after)
docker compose up --build -d

# Or build on a beefier machine and push:
docker buildx build --platform linux/arm64,linux/amd64 \
  -t your-registry/headroom:latest --push .
```

The default `u2netp` rembg model is 4.7MB and runs in 5–15 seconds per photo on
a Pi 4. Bump `HEADROOM_REMBG_MODEL=isnet-general-use` if you want sharper masks
and don't mind the larger model + slower inference.

Photos and the SQLite DB live in the named `headroom-data` volume — back it up
periodically.

---

## Development

```bash
./scripts/setup.sh                           # One-shot setup (--help for flags)
uv run uvicorn headroom.app:app --reload     # Backend (port 8000)
cd frontend && npm run dev                   # Frontend (port 5173)
cd frontend && npm run build                 # Type-check + production SPA build
cd frontend && npm run typecheck             # Type-check only
uv run pytest                                # All tests
uv run pytest tests/test_search.py -k color  # Single test
```

Tests use in-memory SQLite, mock out `rembg` (it's heavy), and never call the
Anthropic API. The pipeline degrades to `analysis_status = "skipped"` when no
API key is configured, so the test contract stays honest.

---

## Architecture

**Backend** (Python 3.12, FastAPI, async SQLAlchemy + aiosqlite):

```
src/headroom/
├── app.py                       # FastAPI factory, lifespan, SPA serving
├── config.py                    # pydantic-settings, env prefix HEADROOM_
├── database.py                  # async engine + inline DDL migrations
├── models/                      # AppSetting, Case, Hat, HatColor, Room
├── schemas/                     # Pydantic I/O models
├── routes/                      # cases, hats, rooms, search, meta, settings, health
├── services/
│   ├── claude_analysis.py       # Vision tool-use call → structured HatAnalysis
│   ├── background_removal.py    # rembg (ONNX) → transparent PNG
│   ├── melin_recap.py           # Brand-aware deep links
│   ├── hat_analysis_pipeline.py # Orchestrates upload → BG removal → Claude → DB
│   ├── settings_service.py      # API key get/set/clear (DB > env)
│   └── case/hat/room/search_service.py
└── utils/photo.py               # Resize / HEIC conversion / filename gen
```

**Frontend** (React 19, Vite, TypeScript, TanStack Query — _no UI framework_):

```
frontend/src/
├── styles/
│   ├── tokens.css               # Synthwave palette + typography + base
│   └── app.css                  # All component styles (replaces Bootstrap)
├── components/
│   ├── layout/                  # AppShell + TopNav + BottomNav + Footer
│   ├── common/                  # Spinner, badge, swatches, lightbox, modal, empty
│   └── photos/                  # PhotoCapture (uses native camera)
├── pages/                       # 12 page components
├── api/                         # Typed fetch clients
└── types/index.ts               # Shared TS interfaces (mirrors Pydantic)
```

**Data model**: Rooms → Cases → Hats. A case holds **either** 4 regular hats OR
6 beanies (mutually exclusive). The Default Room (id=1) cannot be deleted.

---

## License

[GNU AGPL v3.0](LICENSE).
