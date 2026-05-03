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
    return app


@pytest.fixture
def client(app):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")
