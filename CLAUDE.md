# Headroom

FastAPI web API project managed with `uv`, targeting Python 3.12+.

## Commands

- `uv run uvicorn headroom.app:app --reload` — Run dev server
- `uv run pytest` — Run all tests
- `uv run pytest tests/test_routes.py::test_name` — Run single test

## Architecture

- **src/headroom/app.py** — FastAPI app factory (`create_app()`) and module-level `app` instance
- **src/headroom/routes.py** — Route definitions using `APIRouter`
- **tests/** — Tests use `httpx.AsyncClient` with `ASGITransport` for async testing

## Conventions

- Add new routes in `routes.py` (or new route modules) and include them in `app.py`
- Use `pytest-anyio` with `@pytest.mark.anyio` for async tests
- Dev dependencies go in `[dependency-groups] dev` in pyproject.toml
