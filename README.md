# HEADROOM

> _The Outrun-grade vault for your hat collection._

![logo](uploads/branding/logo.png)

Headroom is a self-hosted hat collection tracker with **AI-powered identification**.
Snap a photo and Claude Vision figures out the brand, model, dominant colors, and
estimated retail price. The background gets stripped automatically so every hat
floats on a synthwave canvas. Designed mobile/iPad-first, runs in a Docker
container on a Raspberry Pi, looks like 1986.

---

## What's new in 0.2 — "Outrun"

- 🎨 **Total UI rebuild** — synthwave/retro-80s design system. Neon magenta on
  near-black. Sunset gradients. Audiowide + Orbitron typography. Mobile/iPad-first
  with bottom nav, large tap targets, and a sticky filter bar.
- 🧠 **Claude Vision analysis** — every hat photo is sent to `claude-sonnet-4-6`
  via tool-use to extract brand, specific model, style descriptor, primary /
  secondary / tertiary colors with hex, design notes, and an estimated new
  retail price.
- ✂️ **Automatic background removal** — `rembg` (ONNX-based, Pi-friendly)
  cuts the hat out and saves it as a transparent PNG.
- 💰 **Pricing tiles** — best-effort original retail price (from Claude) and a
  deep link into [Melin Recap](https://www.melinrecap.com) for live resale
  comparables on Melin hats.
- 🔑 **Settings UI for the API key** — store the Anthropic key in the database
  via the Settings page (masked on read), or fall back to an environment
  variable. Includes a "Test connection" button.
- 🔄 **Reanalyze** — re-run Claude on an existing photo without re-uploading.
- 🐳 **Dockerfile + docker-compose** — multi-stage build, runs as a non-root
  user, pre-caches the rembg model, multi-arch (amd64 + arm64 for Pi 4 / 5).

See [CHANGELOG.md](CHANGELOG.md) for the full diff.

---

## Quick start

### Docker (recommended — works on Mac, Linux, Pi)

```bash
git clone <repo-url> && cd headroom
docker compose up -d --build
```

Then open http://localhost:8000 and head to **Settings** to paste your
Anthropic API key.

> The first build takes a few minutes (it pre-downloads the rembg model so
> your Pi doesn't have to). Subsequent builds are cached.

To pre-bake your API key as a fallback default, edit
[`docker-compose.yml`](docker-compose.yml) and uncomment the
`HEADROOM_ANTHROPIC_API_KEY` line.

### Local dev (no Docker)

Prereqs: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 20+, npm.

```bash
git clone <repo-url> && cd headroom
./scripts/setup.sh        # uv sync + npm install + create upload dirs

# terminal 1 — backend (port 8000)
uv run uvicorn headroom.app:app --reload

# terminal 2 — frontend dev server (port 5173, proxies to backend)
cd frontend && npm run dev
```

For production: `cd frontend && npm run build`, then run uvicorn — the FastAPI
app serves the built SPA from `frontend/dist`.

---

## Configuring the AI features

The AI features need an Anthropic API key. **The DB-stored key always wins** over
the environment variable, so you can ship a docker-compose default and let users
override it from the UI.

| Source | When | Set via |
|---|---|---|
| **Database** (preferred) | Set per-user from the Settings page; persists across restarts | UI: Settings → Claude API Key |
| **Environment** (fallback) | Useful as a default for fresh installs | `HEADROOM_ANTHROPIC_API_KEY` |

If no key is configured, photo upload still works — the hat just gets
`analysis_status = "skipped"` and you can fill in the pricing fields manually.
You can drop a key in later and use the **Reanalyze** button on any hat detail
page to backfill.

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

When Claude identifies a hat as a Melin model, the hat record gets a deep link
to the matching filter page on melinrecap.com. We deliberately don't fabricate a
single resale number — the marketplace is JS-rendered and prices fluctuate, so
we link out for live comparables instead. You can always set
`resale_price` manually from the Edit Hat page.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `HEADROOM_DATABASE_URL` | `sqlite+aiosqlite:///./headroom.db` | DB connection string |
| `HEADROOM_UPLOAD_DIR` | `uploads` | Where photos live on disk |
| `HEADROOM_CORS_ORIGINS` | `["http://localhost:5173"]` | Allowed CORS origins (JSON list) |
| `HEADROOM_ANTHROPIC_API_KEY` | _(unset)_ | Default API key (overridden by DB value) |
| `HEADROOM_ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Claude model to use for vision |
| `HEADROOM_REMBG_MODEL` | `u2netp` | rembg model name (`u2netp` is Pi-friendly; `u2net` / `isnet-general-use` are higher quality but ~170MB) |
| `HEADROOM_HTTP_TIMEOUT` | `30.0` | Outbound HTTP timeout in seconds |
| `HEADROOM_ADMIN_TOKEN` | _(unset)_ | If set, `/api/settings/api-key` and `/api/admin/*` require `Authorization: Bearer <token>`. Unset → endpoints are open (single-user-LAN default) with a startup warning. |
| `HEADROOM_LOG_LEVEL` | `INFO` | Default log level when no root handlers are configured (i.e. when running uvicorn directly). |
| `HEADROOM_BACKUP_ENABLED` | `true` | Set to `false` to disable scheduled backups (one-click download still works). |
| `HEADROOM_BACKUP_INTERVAL_HOURS` | `24` | How often the background scheduler writes a tarball to `/data/backups/`. |
| `HEADROOM_BACKUP_RETENTION_DAYS` | `7` | How many timestamped backups to keep on disk. Older ones are pruned after each new write. |

---

## Running on a Raspberry Pi

The Docker image is built as multi-arch (amd64 + arm64). On a Pi 4 / 5 running
64-bit Raspberry Pi OS or Ubuntu Server:

```bash
# Build on the Pi (slow first build, fine after)
docker compose up -d --build

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
uv run uvicorn headroom.app:app --reload   # Backend (port 8000)
cd frontend && npm run dev                  # Frontend (port 5173)
cd frontend && npm run build                # Production SPA build
cd frontend && npx tsc -b --noEmit         # Type-check
uv run pytest                               # All tests
uv run pytest tests/test_search.py -k color # Single test
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
