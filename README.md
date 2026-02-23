# Headroom

![image](uploads/branding/logo.png)
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
mkdir -p uploads/cases uploads/hats uploads/branding  # Create upload directories
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

```bash
uv run uvicorn headroom.app:app --host 0.0.0.0 --port 8000
```

To change the port, pass a different `--port` value:

```bash
uv run uvicorn headroom.app:app --host 0.0.0.0 --port 3000
```

You can also set the port via the `UVICORN_PORT` environment variable:

```bash
UVICORN_PORT=3000 uv run uvicorn headroom.app:app --host 0.0.0.0
```

## Site Logo

You can upload a custom logo through the web UI:

1. Navigate to **Settings** (gear icon in the navbar, or `/settings`)
2. Click **Upload Logo** and select an image (JPEG, PNG, WebP, or HEIC)
3. The image is automatically resized proportionally (max 96px tall) without skewing
4. The logo appears in the navbar and the homepage hero section
5. You can replace or remove the logo at any time from the same page

Logo files are stored in `uploads/branding/`.

## Testing

```bash
uv run pytest
```

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE).
