import os

# Disable scheduled backups + the import worker before app code imports run.
os.environ.setdefault("HEADROOM_BACKUP_ENABLED", "false")
os.environ.setdefault("HEADROOM_IMPORT_WORKER_ENABLED", "false")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from headroom.database import Base, get_db


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param


# In-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite://"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def isolated_upload_dir(tmp_path, monkeypatch):
    """Point uploads at a per-test temp dir.

    `settings.upload_dir` defaults to the relative `uploads/` path, so without
    this, every photo-upload test deposits synthetic images into the
    developer's real uploads folder (which is exactly what happened — tiny
    solid-color squares accumulated there for months).
    """
    from headroom.config import settings

    upload_dir = tmp_path / "uploads"
    # Mirror what the app lifespan creates (it doesn't run under ASGITransport).
    for sub in ("cases", "hats", "branding"):
        (upload_dir / sub).mkdir(parents=True)
    monkeypatch.setattr(settings, "upload_dir", upload_dir)


@pytest.fixture(autouse=True)
def no_live_melin_marketplace(monkeypatch):
    """Tests never call the live Sharetribe API (house rule: no external APIs).

    `_query_listings` is the single network seam in melin_recap; raising
    MelinRecapError exercises the degrade-to-link-only path. Individual tests
    re-patch it with canned data.
    """
    from headroom.services.melin_recap import MelinRecapError

    async def _no_network(_params):
        raise MelinRecapError("live marketplace disabled in tests")

    monkeypatch.setattr(
        "headroom.services.melin_recap._query_listings", _no_network
    )


@pytest.fixture(autouse=True)
def stub_background_removal(monkeypatch):
    """rembg is heavy and downloads model weights on first use — never run it in tests.

    The pipeline accepts `None` as 'background removal failed' and falls back
    to the processed JPEG, which is exactly what we want for the test contract.
    """
    async def _noop(_input, _output):
        return None

    monkeypatch.setattr(
        "headroom.services.background_removal.remove_background", _noop
    )
    monkeypatch.setattr(
        "headroom.services.hat_analysis_pipeline.remove_background", _noop
    )


@pytest.fixture(autouse=True)
async def setup_db():
    from headroom.models import __all_models__  # noqa: F811
    from headroom.models.room import Room

    _ = __all_models__
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        result = await session.execute(select(Room).where(Room.id == 1))
        if not result.scalar_one_or_none():
            session.add(Room(id=1, name="Default Room"))
            await session.commit()

    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session() -> AsyncSession:
    async with test_session_factory() as session:
        yield session


@pytest.fixture
def app():
    from headroom.app import create_app

    app = create_app()

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    # The auth gate middleware resolves sessions through this factory.
    app.state.session_factory = test_session_factory
    return app


# One argon2 hash for the whole run — hashing per-test would be slow.
_TEST_PASSWORD = "test-password-123"
_TEST_SESSION_ID = "test-session-cookie-value"


async def _seed_owner():
    """Insert the test owner + a valid session row directly (no HTTP)."""
    from datetime import datetime, timedelta, timezone

    from headroom.models.user import AuthSession, User
    from headroom.services import auth_service

    global _TEST_HASH
    if "_TEST_HASH" not in globals():
        _TEST_HASH = auth_service.hash_password(_TEST_PASSWORD)

    async with test_session_factory() as session:
        user = User(
            username="testowner",
            password_hash=_TEST_HASH,
            api_token="hr_test-api-token",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        session.add(
            AuthSession(
                id=_TEST_SESSION_ID,
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        await session.commit()
        return user


@pytest.fixture
async def client(app):
    """Authenticated client — the default for the suite."""
    await _seed_owner()
    transport = ASGITransport(app=app)
    c = AsyncClient(transport=transport, base_url="http://test")
    c.cookies.set("headroom_session", _TEST_SESSION_ID)
    return c


@pytest.fixture
def anon_client(app):
    """Unauthenticated client for auth-flow tests (no seeded user)."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")
