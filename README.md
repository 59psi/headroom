# Headroom

Hat collection tracker — FastAPI REST API + React SPA frontend.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Node.js 18+
- npm

## Quick Start

```bash
git clone <repo-url> && cd headroom
./scripts/setup.sh
```

Or manually:

```bash
uv sync                          # Install Python dependencies
cd frontend && npm install       # Install JS dependencies
mkdir -p uploads/cases uploads/hats  # Create upload directories
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HEADROOM_DATABASE_URL` | `sqlite+aiosqlite:///./headroom.db` | Database connection string |
| `HEADROOM_UPLOAD_DIR` | `uploads` | Directory for uploaded photos |
| `HEADROOM_CORS_ORIGINS` | `["http://localhost:5173"]` | Allowed CORS origins (JSON list) |

## Development

**Backend** (port 8000):

```bash
uv run uvicorn headroom.app:app --reload
```

**Frontend** dev server (port 5173, proxies API to backend):

```bash
cd frontend && npm run dev
```

## Production Build

```bash
cd frontend && npm run build
```

Then run the backend only — it serves the built SPA from `frontend/dist`.

## Testing

```bash
uv run pytest
```
