import os

# Disable scheduled backups, the import worker, and mDNS advertising before
# app code imports run.
os.environ.setdefault("HEADROOM_BACKUP_ENABLED", "false")
os.environ.setdefault("HEADROOM_IMPORT_WORKER_ENABLED", "false")
# Off by design, not convenience: with the worker running, photo analysis is
# queued and the upload route returns before it finishes, so every test that
# asserts on analysis results would race it. Off, the route runs the pipeline
# inline — the same code, synchronously. tests/test_analysis_queue.py drives
# the queued path explicitly.
os.environ.setdefault("HEADROOM_ANALYSIS_WORKER_ENABLED", "false")
os.environ.setdefault("HEADROOM_MDNS_ENABLED", "false")
# Sweeps the whole collection against the marketplace API — never in tests.
os.environ.setdefault("HEADROOM_REPRICING_ENABLED", "false")

# The MODULE-LEVEL engine must be unreachable from a test, so it points at a
# path that cannot be opened. Assigned, not `setdefault`: a developer's shell
# exporting a real URL must not turn the suite loose on a real database.
#
# Every test runs against `test_engine` below, and app code reaches the
# database through seams — `get_db` (overridden), `app.state.session_factory`
# / `app.state.engine` (set on the fixture), `reprice_once(session_factory=)`.
# Anything that instead imports `database.engine` or `database.async_session`
# works in production and quietly talks to a different database in every test.
# That was not hypothetical: `settings.database_url` defaulted to
# `./headroom.db`, and a bare `checkpoint_wal()` in one test created that file
# in the working directory and touched its WAL sidecars on every run for weeks
# — empty, so harmless, and invisible for exactly that reason. With this URL
# the same mistake raises `unable to open database file` on the spot.
os.environ["HEADROOM_DATABASE_URL"] = (
    "sqlite+aiosqlite:////nonexistent/headroom-tests-must-not-reach-the-module-engine.db"
)

# Tests never call an external API — but the WORKER flags above only stop the
# background paths, not the keys. `config.py` reads these at import and
# `settings_service.get_*_key` falls back to the environment when the DB has
# none, so a developer or CI runner with either exported made the suite issue
# real, billable requests. It only ever "held" by accident of one machine's
# shell. Cleared before any app module is imported.
for _leaky in (
    "HEADROOM_ANTHROPIC_API_KEY",
    "HEADROOM_GOOGLE_VISION_API_KEY",
    "HEADROOM_EBAY_APP_ID",
    "HEADROOM_EBAY_CERT_ID",
):
    os.environ.pop(_leaky, None)

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
    # No `cases/`: there is deliberately no case-photo feature, and the lifespan
    # creates no such directory either.
    for sub in ("hats", "branding"):
        (upload_dir / sub).mkdir(parents=True)
    monkeypatch.setattr(settings, "upload_dir", upload_dir)


@pytest.fixture(autouse=True)
def fresh_rate_limiter():
    """The login rate limiter and its block log are module-level dicts.

    Tests used to clear them AFTER their assertions, so a failing assertion
    leaked five to twenty recorded failures into whatever ran next — and the
    next login test then hit a lockout it did not cause. Reset both before and
    after every test, in one place.
    """
    from headroom.services import auth_service

    auth_service._failures.clear()
    auth_service._blocked_logged.clear()
    yield
    auth_service._failures.clear()
    auth_service._blocked_logged.clear()


@pytest.fixture(autouse=True)
def no_live_melin_marketplace(monkeypatch):
    """Tests never call the live Sharetribe API (house rule: no external APIs).

    `query_listings` is the single network seam in melin_recap; raising
    MelinRecapError exercises the degrade-to-link-only path. Individual tests
    re-patch it with canned data.
    """
    from headroom.services.melin_recap import MelinRecapError

    async def _no_network(_params):
        raise MelinRecapError("live marketplace disabled in tests")

    monkeypatch.setattr(
        "headroom.services.melin_recap.query_listings", _no_network
    )


@pytest.fixture(autouse=True)
def no_outbound_http(monkeypatch):
    """No test reaches any host, whatever key it managed to store.

    The Sharetribe fixture above blocks one seam, and popping the API keys
    out of the environment blocks the others — until a test stores a key
    through `PUT /api/settings/api-key` (which `test_settings_api.py` does)
    and a later one uploads a photo without stubbing the analyzer. A review
    agent did exactly that by accident and this suite made ONE real request
    to `api.anthropic.com` with a bogus key. The SDK runs on `httpx2`, the
    app's own clients on `httpx`; both transports are cut at the socket
    here. Tests that need a wire shape hand the SDK a `MockTransport`, which
    never reaches this method.
    """
    import httpx

    def _refuse(self, request):
        raise httpx.ConnectError(
            f"outbound HTTP is disabled in tests (tried {request.url.host})", request=request
        )

    async def _refuse_async(self, request):
        _refuse(self, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _refuse_async)
    try:
        import httpx2
    except ImportError:  # pragma: no cover - the SDK's transport, if present
        return

    def _refuse2(self, request):
        raise httpx2.ConnectError(
            f"outbound HTTP is disabled in tests (tried {request.url.host})", request=request
        )

    async def _refuse2_async(self, request):
        _refuse2(self, request)

    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", _refuse2)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", _refuse2_async)


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
    from headroom.models import __all_models__
    from headroom.models.room import Room

    _ = __all_models__
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        result = await session.execute(select(Room).where(Room.id == 1))
        if not result.scalar_one_or_none():
            # is_default mirrors what database.ensure_default_room() seeds in
            # production — it's the flag, not the id, that makes this the
            # fallback room, so the fixture has to set it or case creation
            # would fall back to "lowest id" by accident rather than by design.
            session.add(Room(id=1, name="Default Room", is_default=True))
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
    # The auth gate middleware, `error_handler` AND the lifespan all resolve
    # sessions through this factory, and the lifespan runs `init_db` and the
    # shutdown checkpoint on this engine. Both must point at the test database:
    # before the lifespan took them from `app.state`, booting it under test
    # would have created a `headroom.db` in the working directory — which is
    # why no test ever booted it, and why the app's wiring went unverified.
    app.state.session_factory = test_session_factory
    app.state.engine = test_engine
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


# ---- a FILE-backed database, for concurrency ------------------------------ #
#
# The in-memory engine above is a `StaticPool`: one connection shared by every
# session. That is right for a request test holding one session and wrong for
# anything that runs several at once — one session's `close()` issues ROLLBACK
# on the shared connection and discards another's uncommitted write. A race
# test needs each request on its own connection, as production has, so these
# fixtures build the same app over a real SQLite file with the production
# connect hook attached. `tests/test_lifespan_wiring.py` does the same for
# boots; this is the request-level twin.


@pytest.fixture
async def file_engine(tmp_path):
    from sqlalchemy import event

    from headroom import database
    from headroom.models.room import Room

    url = f"sqlite+aiosqlite:///{tmp_path / 'race.db'}"
    engine = create_async_engine(url, echo=False)
    event.listen(engine.sync_engine, "connect", database._sqlite_pragmas)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(database.Base.metadata.create_all)
    async with factory() as db:
        db.add(Room(id=1, name="Default Room", is_default=True))
        await db.commit()
    yield engine, factory
    await engine.dispose()


@pytest.fixture
def file_app(file_engine):
    from headroom.app import create_app

    engine, factory = file_engine
    app = create_app()

    async def override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.state.session_factory = factory
    app.state.engine = engine
    return app


@pytest.fixture
async def file_client(file_app, file_engine):
    """Authenticated client whose every request gets its own connection."""
    from datetime import datetime, timedelta, timezone

    from headroom.models.user import AuthSession, User
    from headroom.services import auth_service

    _, factory = file_engine
    global _TEST_HASH
    if "_TEST_HASH" not in globals():
        _TEST_HASH = auth_service.hash_password(_TEST_PASSWORD)
    async with factory() as db:
        user = User(username="fileowner", password_hash=_TEST_HASH, api_token="hr_file-token")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        db.add(AuthSession(
            id="file-session", user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        ))
        await db.commit()
    c = AsyncClient(transport=ASGITransport(app=file_app), base_url="http://test")
    c.cookies.set("headroom_session", "file-session")
    return c
