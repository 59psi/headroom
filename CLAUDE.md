# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- `uv run uvicorn headroom.app:app --reload` — Run backend dev server (port 8000)
- `cd frontend && npm run dev` — Run frontend dev server (port 5173, proxies to backend)
- `cd frontend && npx vite build` — Production build (output: frontend/dist, served by backend)
- `cd frontend && npx tsc -b --noEmit` — TypeScript type-check
- `uv run pytest` — Run all tests (must run from project root)
- `uv run pytest tests/test_search.py::test_search_by_style` — Run single test

## Architecture

**Backend** (Python 3.12+, FastAPI, SQLAlchemy async + aiosqlite):
- `src/headroom/app.py` — App factory with lifespan, CORS, SPA serving from frontend/dist
- `src/headroom/routes/` — API routers: health, cases, hats, rooms, search, meta, settings
- `src/headroom/models/` — SQLAlchemy models: Case, Hat, HatColor, Room
- `src/headroom/services/` — Business logic: case, hat, color, room, search services
- `src/headroom/schemas/` — Pydantic request/response schemas
- `src/headroom/database.py` — Engine, session, init_db with inline migrations + default room seeding
- `src/headroom/config.py` — Pydantic-settings, env prefix `HEADROOM_`

**Frontend** (React 19, TypeScript, Vite, TanStack Query, Bootstrap 5):
- `frontend/src/pages/` — Page components (Home, Hats, Cases, Rooms, Search, Settings)
- `frontend/src/components/` — Shared components (layout, photos, common)
- `frontend/src/api/` — API client functions (hats, cases, rooms, search, settings)
- `frontend/src/types/index.ts` — TypeScript interfaces matching backend schemas

**Tests** (pytest-anyio, httpx AsyncClient + ASGITransport):
- `tests/` — Async tests, in-memory SQLite, conftest seeds default room

## Key Patterns

- **Async relationship loading**: Always use `selectinload()` for relationships; after commit + relationship changes, call `db.expire_all()` then re-query (see `_reload_hat()`, `_reload_case()`)
- **Database migrations**: `database.py:_run_migrations()` handles ALTER TABLE for existing DBs (no Alembic); `ensure_default_room()` uses raw SQL to avoid cascade
- **Domain model**: Rooms contain Cases, Cases contain Hats. Cases are type-exclusive (4 regular hats OR 6 beanies). Default Room (id=1) cannot be deleted
- **Color detection**: Photo upload → Pillow resize → ColorThief extracts 4 dominant colors → each gets `color_name` (CSS3), `general_color` (human-friendly), `hex_value`
- **Search**: Multi-term AND across style/condition/size/colors/room. Default searches `general_color`; `exact_colors=true` searches `color_name`
- **Query keys**: `['rooms']` for full RoomRead[], `['meta', 'rooms']` for dropdown options — invalidate both on room mutations

## Conventions

- Routes in `src/headroom/routes/`, register in `routes/__init__.py`
- `@pytest.mark.anyio` for async tests, asyncio backend only (no trio)
- Dev dependencies in `[dependency-groups] dev` in pyproject.toml
- Frontend API functions in `frontend/src/api/`, types in `frontend/src/types/`
