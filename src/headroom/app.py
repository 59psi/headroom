from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from headroom.config import settings
from headroom.database import init_db
from headroom.routes import api_router

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / "cases").mkdir(exist_ok=True)
    (settings.upload_dir / "hats").mkdir(exist_ok=True)
    (settings.upload_dir / "branding").mkdir(exist_ok=True)
    await init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Headroom", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    if settings.upload_dir.exists():
        app.mount(
            "/uploads",
            StaticFiles(directory=str(settings.upload_dir)),
            name="uploads",
        )

    # Serve built frontend (SPA fallback)
    if FRONTEND_DIST.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=str(FRONTEND_DIST / "assets")),
            name="frontend-assets",
        )

        @app.get("/{full_path:path}")
        async def serve_spa(request: Request, full_path: str):
            # Serve index.html for all non-API, non-static routes (SPA routing)
            file_path = FRONTEND_DIST / full_path
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
