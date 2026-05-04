---
agent: triage
version: 1.0
target: /Users/brandon/Things/Headroom @ a2efd86 (full repo)
confidence: high
findings:
  - "Self-hosted hat-collection tracker. Python 3.12 / FastAPI / SQLAlchemy-async / aiosqlite backend; React 19 / Vite / TS frontend, no UI framework. Single-machine deployment via Docker, designed for Raspberry Pi."
  - "Two domains in one repo: (a) the original CRUD app (rooms → cases → hats), and (b) a freshly-added AI pipeline (Claude Vision analysis + rembg background removal + Melin Recap deep-linking)."
  - "Recent activity is heavily concentrated in v0.2.0 'Outrun' — a same-day total UI rebuild plus the entire AI pipeline. Three fix commits followed (Docker hatchling, navbar padding, logo seeding)."
  - "Total ~7,600 LOC across backend (~2.2k), tests (~960), frontend (~4.4k including CSS)."
  - "64 tests passing, all in-memory SQLite, async via pytest-anyio. rembg + Anthropic SDK explicitly mocked/disabled in tests."
  - "Dockerfile multi-stage, runs as non-root, multi-arch; volume at /data. Pre-caches the rembg model at build time."
open_questions:
  - "Is this a single-user or shared deployment? README implies single-user-on-Pi but there's no auth at all on the API."
  - "What hat collection size is realistic? (1k? 10k?) — affects scaling concerns."
red_flags: []
artifacts:
  - "00-triage-dispatch.md"
---

# Intake Report — Headroom @ HEAD

## Target

- **Path**: `/Users/brandon/Things/Headroom`
- **HEAD**: `a2efd86` ("feat(branding): seed default logo …") on `main`
- **Scope**: full-program (backend + frontend + infra + tests + docs)
- **Depth**: standard

## Quick stats

| Area | LOC | Files |
|---|---:|---:|
| Backend (`src/`) | 2,232 | ~32 .py |
| Tests (`tests/`) | 959 | 8 .py |
| Frontend (`frontend/src/`) | 4,453 | 35 .ts/.tsx/.css |
| **Total source** | **~7,644** | **80** |

## Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2 (async), aiosqlite, pydantic-settings, Pillow / pillow-heif, rembg + onnxruntime, anthropic SDK ≥ 0.40, httpx, beautifulsoup4 (unused so far), hatchling build backend, uv package manager.
- **Frontend**: React 19, Vite 6, TypeScript 5.8, TanStack Query 5, react-router-dom 7. **No UI framework** — Bootstrap was dropped in v0.2.0; all styling is custom CSS in `frontend/src/styles/`.
- **Storage**: SQLite via aiosqlite. Single DB file at `/data/headroom.db` in Docker.
- **Deployment**: Docker (multi-stage, multi-arch amd64+arm64). Designed for Raspberry Pi; uses `u2netp` rembg model (~5 MB) by default.

## Character

- **Type**: refactor + greenfield-AI-pipeline. v0.2.0 was a near-total UI rebuild plus a brand-new Claude analysis pipeline. The CRUD core (rooms / cases / hats) is much older and untouched in this release.
- **Activity profile**: heavy bursts followed by quiet. The current release was written in a single concentrated session; pre-v0.2.0 commits were small incremental fixes.
- **Tests**: present and credible (64 passing). `rembg` is explicitly stubbed via autouse fixture in `tests/conftest.py`. Anthropic API is never called in tests — pipeline degrades to `analysis_status='skipped'` when no key is present.

## Notable design decisions (descriptive, not interpretive)

- DB-stored Anthropic API key takes precedence over env var (`HEADROOM_ANTHROPIC_API_KEY`).
- Hat photos go through a multi-step pipeline: resize/HEIC convert → rembg → Claude Vision tool-use → DB writes. Each step degrades independently.
- Resale prices are intentionally **not** scraped from melinrecap.com — site is JS-rendered. The app emits a deep link to the brand+style filter page instead.
- Inline DDL migrations in `database.py` use only static SQL strings (no f-string interpolation into `text()`).
- Dockerfile bundles a `seed/branding/` directory; the FastAPI lifespan copies any seed files into the empty volume on first boot, idempotent across restarts.
