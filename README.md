# HEADROOM

> _The Outrun-grade vault for your hat collection._

![logo](seed/branding/logo.png)

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-ff2eb6.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-00f0ff.svg)](pyproject.toml)
[![React 19](https://img.shields.io/badge/React-19-00f0ff.svg)](frontend/package.json)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-ff2eb6.svg)](src/headroom/app.py)
[![Self‑hosted](https://img.shields.io/badge/self--hosted-Pi--friendly-b14eff.svg)](docs/OPERATIONS.md)

Headroom is a self-hosted inventory for serious hat collections. Snap a photo
and Claude Vision identifies the brand, model, and colors, estimates retail
price, and pulls live resale comps. The background is stripped automatically so
every hat floats on a synthwave canvas. Built mobile-first, runs on a Raspberry
Pi, secured for the open internet, looks like 1986.

**Docs:** [Usage guide](docs/USAGE.md) — the app end-to-end ·
[Operations guide](docs/OPERATIONS.md) — deploy, configure, back up,
upgrade, troubleshoot · [CHANGELOG](CHANGELOG.md)

---

## Why it exists

Hundreds of hats in identical cases means two daily problems: *"where is my
light-blue one?"* and *"what is all of this actually worth?"* Headroom answers
both — perceptual color search over every photo, a location breadcrumb on every
result, and three independent price signals per hat.

## What it does

**🧠 Identify**
- **Claude Vision analysis** — brand, specific model, tiered colors with hex,
  design notes, estimated retail price. One tool-use call per photo, prompt
  caching enabled.
- **Works without any keys** — background removal and dominant-color detection
  run locally (colors are read *only* from the hat's cutout mask, so the
  background can never contaminate them). Add a Google Vision key for
  logo-based brand detection as a fallback when Claude is unavailable.
- **Automatic background removal** — `rembg` (ONNX, runs on a Pi) turns every
  photo into a transparent PNG.
- **Colorway catalog** — harvests every "Model – Colorway" name circulating on
  the melinrecap resale market (including years of sold-out drops) to power
  autocomplete and purchase matching.

**🔎 Find**
- **Search by color** — tap a swatch (or pick any color) and hats rank by
  *perceptual* closeness (ΔE in LAB space) over their stored hex values. A hat
  whose secondary color matches still surfaces. "Light blue" works no matter
  what the analyzer called it.
- **Text search** — multi-term AND over name, brand, model, style, condition,
  size, colors, and room.
- **Find-it cards** — every result shows the photo, the name, and where it
  physically lives: `📍 Case A-012 · Office`.
- **QR case labels** — print a label sheet; scan a case's QR with your phone
  to open its contents.

**💰 Value**
- **Three price signals per hat** — Claude's retail estimate, eBay
  sold-comparable stats (Browse API), and a **live median resale price** from
  melinrecap's marketplace API (no scraping, no headless browser).
- **Real cost basis** — import order line items from your purchase emails;
  they match to hats and record what you *actually paid*, and when.
- **Valuation dashboard** — totals, retention %, top hats by value, realized
  value from sales, and a wear-rotation nudge.
- **Insurance-grade inventory report** — print-friendly HTML → Save as PDF.

**🧢 Live with it**
- **Rooms → Cases → Hats** with per-case capacity (Melin cases hold 3–4),
  type-exclusive cases, auto-sequenced display IDs.
- **3D-printable case rack** — a modular, stackable, supports-free rack that
  gives each Melin travel case its own slide-in bay. OpenSCAD source + STLs in
  [`hardware/melin-stand-slim.zip`](hardware/melin-stand-slim.zip); print
  notes in [`hardware/`](hardware/README.md).
- **Wear tracking** — one tap logs a wear; get wear counts, cost-per-wear, and
  a list of hats that haven't seen the sun.
- **Three import paths** — single photo with crop/rotate, bulk import (100
  photos through a restart-surviving queue), or straight from the system share
  sheet (Android PWA share target; iOS Shortcut recipe included in-app).
- **Disposition tracking** — sold / gifted / traded / lost / trashed, soft
  delete with undo; sale prices feed realized value.
- **Append-only activity log** — every significant change, auto-pruned.

**🔐 Ship it to the internet**
- **Accounts** — first-run owner setup, argon2id passwords, revocable
  sessions, login rate limiting.
- **Passkeys** — sign in with Face ID / Touch ID (WebAuthn).
- **Everything gated** — the API *and* the photo files require login; raw API
  keys never leave the server (masked reads only).
- **Read-only share links** — show off the collection without handing out a
  login; revocable, optionally expiring.
- **One-command HTTPS** — a Caddy overlay with automatic Let's Encrypt certs.
- **Backups** — scheduled rolling tarballs + one-click download; documented
  restore.

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

When uvicorn reports it's listening, open http://localhost:8000 — the first
visit creates your **owner account**, then head to **Settings** to paste your
Anthropic API key. Once it works, Ctrl-C and relaunch in the background:

```bash
docker compose up --build -d    # detached; follow logs with: docker compose logs -f
```

> **The first build takes a few minutes** (it pre-downloads the rembg model
> so your Pi doesn't have to); later builds are cached. With `-d` your
> terminal returns immediately while the container is still building and
> booting — give it a minute before declaring it broken.

> Errors like **`unknown shorthand flag: 'd' in -d`**, **`docker: 'compose'
> is not a docker command`**, or **`Cannot connect to the Docker daemon`**
> all mean your Docker install is incomplete. Step 2 fixes all of them.

**Putting it on the internet?** Use the HTTPS overlay — Caddy sidecar with
automatic Let's Encrypt certs, passkey identity configured from your domain:

```bash
HEADROOM_DOMAIN=hats.example.com \
  docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
```

See the [Operations guide](docs/OPERATIONS.md) for the full security posture.

### Local (no Docker)

Prereqs: git + curl. The setup script installs everything else it needs —
uv, Python 3.12, Node 20+, backend and frontend deps — via Homebrew on macOS
and apt/dnf on Linux.

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

## Configuring the AI features

The AI features need an Anthropic API key. **The DB-stored key always wins**
over the environment variable, so you can ship a docker-compose default and
let users override it from the UI.

| Source | When | Set via |
|---|---|---|
| **Database** (preferred) | Set from the Settings page; persists across restarts | UI: Settings → Claude API Key |
| **Environment** (fallback) | Useful as a default for fresh installs | `HEADROOM_ANTHROPIC_API_KEY` |

### No Claude key? The fallback

Uploads never depend on Claude. Without a key (or when a Claude call fails),
a basic fallback runs instead and the hat gets `analysis_status = "fallback"`:

- **Colors — always available, no key needed.** Dominant colors are extracted
  locally from the background-removed cutout's alpha mask, so only actual hat
  pixels count.
- **Brand — optional, via Google Cloud Vision logo detection.** Create an API
  key at [console.cloud.google.com](https://console.cloud.google.com/apis/library/vision.googleapis.com)
  (enable the *Cloud Vision API*, then *Credentials → Create API key*) and
  paste it in **Settings → Google Vision Key**. Free tier is 1,000
  requests/month — plenty.

Model name, price estimate, and design notes stay empty in fallback mode —
drop a Claude key in later and hit **Reanalyze** on any hat to upgrade.

### Resale prices (Melin)

Melin hats get a **live median asking price** from melinrecap.com's public
marketplace API (it's a Treet marketplace on Sharetribe Flex — we use the
same anonymous API its own frontend uses), scoped to your exact model when
enough listings match, plus a deep link to browse the comps. Degrades to
link-only if the API is unreachable.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `HEADROOM_DATABASE_URL` | `sqlite+aiosqlite:///./headroom.db` | DB connection string |
| `HEADROOM_UPLOAD_DIR` | `uploads` | Where photos live on disk |
| `HEADROOM_CORS_ORIGINS` | `["http://localhost:5173"]` | Allowed CORS origins (JSON list) |
| `HEADROOM_ANTHROPIC_API_KEY` | _(unset)_ | Default API key (overridden by DB value) |
| `HEADROOM_ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Claude model for vision analysis |
| `HEADROOM_GOOGLE_VISION_API_KEY` | _(unset)_ | Fallback brand (logo) detection. DB value wins |
| `HEADROOM_MELIN_CLIENT_ID` | _(baked in)_ | Public Sharetribe client id for live Melin resale stats |
| `HEADROOM_EBAY_APP_ID` / `HEADROOM_EBAY_CERT_ID` | _(unset)_ | eBay Browse API comps (Production keyset) |
| `HEADROOM_RP_ID` | `localhost` | Passkey relying-party id — must equal the serving domain (HTTPS overlay sets it) |
| `HEADROOM_ORIGIN` | `http://localhost:8000` | Full origin for passkey verification (HTTPS overlay sets it) |
| `HEADROOM_REMBG_MODEL` | `u2netp` | rembg model (`u2netp` is Pi-friendly; `isnet-general-use` is sharper, ~170MB) |
| `HEADROOM_HTTP_TIMEOUT` | `30.0` | Outbound HTTP timeout in seconds |
| `HEADROOM_LOG_LEVEL` | `INFO` | Log level when running uvicorn directly |
| `HEADROOM_BACKUP_ENABLED` | `true` | Scheduled backups on/off |
| `HEADROOM_BACKUP_INTERVAL_HOURS` | `24` | Scheduled backup cadence |
| `HEADROOM_BACKUP_RETENTION_DAYS` | `7` | Rolling backups kept on disk |
| `HEADROOM_IMPORT_WORKER_ENABLED` | `true` | Bulk-import background worker |
| `HEADROOM_ACTIVITY_LOG_RETENTION_DAYS` | `90` | Audit rows kept (pruned daily) |

---

## Running on a Raspberry Pi

The Docker image is multi-arch (amd64 + arm64). On a Pi 4/5 running 64-bit
Raspberry Pi OS or Ubuntu Server:

```bash
# Build on the Pi (slow first build, fine after)
docker compose up --build -d

# Or build on a beefier machine and push:
docker buildx build --platform linux/arm64,linux/amd64 \
  -t your-registry/headroom:latest --push .
```

The default `u2netp` rembg model is 4.7MB and runs in 5–15 seconds per photo
on a Pi 4. Photos, database, and backups live in the `headroom-data` volume —
see [OPERATIONS.md §4](docs/OPERATIONS.md#4-backups--restore) for the backup
and restore procedure.

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

Tests use in-memory SQLite, stub out `rembg`, authenticate through a seeded
test session, and never call the Anthropic, Google, eBay, or Sharetribe APIs
— every external boundary has a test seam.

## Architecture

**Backend** — Python 3.12, FastAPI, async SQLAlchemy + aiosqlite:

```
src/headroom/
├── app.py                       # factory, lifespan, SPA serving, auth gate
├── auth.py                      # session/token guards + gate middleware
├── config.py                    # pydantic-settings (HEADROOM_*)
├── database.py                  # async engine + inline DDL migrations
├── models/                      # User, Case, Hat, HatColor, WearLog, Purchase,
│                                #  ColorwayEntry, ShareLink, ImportJob, …
├── routes/                      # auth, hats, cases, rooms, search, meta,
│                                #  settings, admin, import_jobs, share_links
└── services/
    ├── claude_analysis.py       # Claude Vision tool-use → structured result
    ├── background_removal.py    # rembg (ONNX) → transparent PNG
    ├── color_extraction.py      # mask-only colors + LAB distance + palette
    ├── google_vision.py         # fallback brand via logo detection
    ├── melin_recap.py           # live resale median (Sharetribe public API)
    ├── catalog_service.py       # colorway harvest + purchase matching
    ├── auth_service.py          # argon2, sessions, rate limiting
    ├── passkey_service.py       # WebAuthn ceremonies
    ├── label_service.py         # QR case-label sheet (inline SVG)
    ├── hat_analysis_pipeline.py # upload → bg-removal → analyze → price
    ├── import_service.py        # restart-surviving bulk-import worker
    └── backup_service.py        # scheduled + on-demand tar.gz
```

**Frontend** — React 19, Vite, TypeScript, TanStack Query, zero UI framework:
hand-rolled synthwave design system in two CSS files, PWA-installable, native
`<datalist>` autocomplete, hand-rolled WebAuthn plumbing. No component
library, no CSS framework, no state-management dependency.

**Data model**: Rooms → Cases → Hats. Cases are type-exclusive (regular or
beanie) with per-case capacity. The Default Room cannot be deleted. Disposed
hats keep their history but free their slot.

---

## License

[GNU AGPL v3.0](LICENSE).
