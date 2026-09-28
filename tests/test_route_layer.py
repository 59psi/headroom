"""The route layer's own mechanisms: path matching, error translation, wire types.

Each test here pins a mechanism rather than one endpoint's behavior, because
every one of these was a rule that held by convention — an ordering comment, a
service that happened to raise the right HTTP status — and nothing failed the
day the convention was broken.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

import headroom.routes as routes_pkg
import headroom.schemas as schemas_pkg
from headroom.database import get_db
from headroom.routes import _api
from headroom.services import errors

pytestmark = pytest.mark.anyio

_ROOT = Path(__file__).resolve().parents[1]


def _route_modules():
    for info in pkgutil.walk_packages(routes_pkg.__path__, routes_pkg.__name__ + "."):
        yield importlib.import_module(info.name)


# ---- /api/hats/import vs /api/hats/{hat_id} ---------------------------- #


async def test_get_hats_import_lists_jobs(client):
    """What `BulkImportPage`'s recent-jobs list calls. Under the wrong route
    order it answered 422 "hat_id is not an integer", and the whole suite
    stayed green because only the POST was ever exercised."""
    resp = await client.get("/api/hats/import?limit=1")

    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_hat_routes_cannot_shadow_the_import_routes_in_either_order():
    """The collision is closed by the path itself, not by registration order.

    The hat router goes in FIRST here — the order `routes/__init__.py` used to
    warn against. `{hat_id:int}` only matches digits, so `import` still falls
    through to the bulk-import router.
    """
    from headroom.routes.hats import router as hats_router
    from headroom.routes.import_jobs import router as import_jobs_router
    from tests.conftest import test_session_factory

    app = FastAPI()
    app.include_router(hats_router)
    app.include_router(import_jobs_router)

    async def _db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/hats/import?limit=1")

    assert resp.status_code == 200, resp.text
    assert resp.json() == []


# ---- domain errors → HTTP ---------------------------------------------- #


async def test_every_router_translates_domain_errors():
    """A router built without `DomainErrorRoute` answers a service refusal with
    a 500 and an `error.unhandled` row. Every router here must use it — every
    one, not just the attribute named `router`: `share_links` has two, and a
    census that read one name would not see the other.
    """
    from fastapi import APIRouter

    missing = []
    for module in _route_modules():
        routers = [v for v in vars(module).values() if isinstance(v, APIRouter)]
        for router in routers:
            for route in router.routes:
                if isinstance(route, APIRoute) and not isinstance(route, _api.DomainErrorRoute):
                    missing.append(f"{module.__name__}: {sorted(route.methods)} {route.path}")
    assert missing == [], missing


async def test_both_auth_layers_refuse_an_anonymous_caller():
    """`require_user` on every protected router is a real second layer.

    Built with the gate middleware REMOVED, so only the route-level guard is
    left: every operation outside the anonymous allowlist must still answer
    401. Before the routers carried it, 26 routes — deleting a hat, the logo,
    creating a share link, the share target — served an anonymous caller the
    moment anything put a path outside the gate's prefixes.

    Reads as well as writes. The search and meta routers answer GETs only, so
    a census of writes could not see either one moved to the open list — and
    search hands back the collection itself.
    """
    from headroom.app import create_app
    from headroom.auth import AuthGateMiddleware
    from tests.conftest import test_engine, test_session_factory
    from tests.test_security import _is_allowed_anonymous, _operations, _probe_path

    app = create_app()
    app.user_middleware = [m for m in app.user_middleware if m.cls is not AuthGateMiddleware]
    app.middleware_stack = None  # rebuilt from `user_middleware` on first call

    async def _db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _db
    app.state.session_factory = test_session_factory
    app.state.engine = test_engine

    # An owner to impersonate: with an empty users table, a guard that resolved
    # the wrong principal would find nobody and still answer 401.
    from tests.conftest import _seed_owner

    await _seed_owner()

    answered: list[str] = []
    probed = 0
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for method, raw_path in _operations(app):
            if _is_allowed_anonymous(method, raw_path):
                continue
            probed += 1
            resp = await c.request(method, _probe_path(raw_path))
            if resp.status_code != 401:
                answered.append(f"{method} {raw_path} -> {resp.status_code}")
        # Not in the OpenAPI document (no `include_in_schema`), and a write.
        share = await c.post("/share")
        if share.status_code != 401:
            answered.append(f"POST /share -> {share.status_code}")

    # A census that enumerated nothing would pass: reads and writes both counted.
    assert probed > 100, probed
    assert answered == [], "\n  ".join(["answered without the gate:", *answered])


async def test_every_domain_error_has_a_status():
    """A new kind of refusal must be mapped, or it would surface as a 500."""
    kinds = {
        obj for _name, obj in inspect.getmembers(errors, inspect.isclass)
        if issubclass(obj, errors.DomainError) and obj is not errors.DomainError
    }
    assert kinds <= set(_api.STATUS_FOR), sorted(k.__name__ for k in kinds - set(_api.STATUS_FOR))


async def test_the_services_speak_domain_not_http():
    """Services raise `DomainError`s; only the route layer knows about HTTP.

    `hat_service` and its neighbors imported `fastapi.HTTPException`, which is
    how the import worker came to record `"404: Case not found"` on an item.
    EVERY service module, not a hand-picked four: the import and catalog
    services raised HTTP errors too, and a list names only the ones someone
    remembered. Read as imports (the AST), not as text, so a comment that
    tells the story does not trip it and an aliased import does not slip by.
    """
    import ast

    import headroom.services as services_pkg

    offenders = []
    for info in pkgutil.walk_packages(services_pkg.__path__, services_pkg.__name__ + "."):
        module = importlib.import_module(info.name)
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            if any(n.split(".")[0] in ("fastapi", "starlette") for n in names):
                offenders.append(f"{info.name}:{node.lineno}")
    assert offenders == [], f"services importing the web framework: {offenders}"


async def test_a_service_refusal_reads_as_its_sentence(db_session):
    """What a non-HTTP caller records: the sentence, no status code."""
    from headroom.schemas.hat import HatCreate
    from headroom.services import hat_service

    with pytest.raises(errors.NotFound) as excinfo:
        await hat_service.create_hat(
            db_session,
            HatCreate(case_id=99999, condition="new", size="classic", style="a_game"),
        )
    assert str(excinfo.value) == "Case not found"


async def test_a_service_refusal_answers_with_its_mapped_status(client):
    missing_case = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game", "case_id": 99999},
    )
    assert missing_case.status_code == 404
    assert missing_case.json() == {"detail": "Case not found"}

    default_room = next(r for r in (await client.get("/api/rooms")).json() if r["is_default"])
    refused = await client.delete(f"/api/rooms/{default_room['id']}")
    assert refused.status_code == 400
    assert "default room" in refused.json()["detail"]


# ---- uniform error shapes ---------------------------------------------- #


async def test_the_public_logo_404_is_json_like_every_other(anon_client):
    resp = await anon_client.get("/api/public/branding/logo")

    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert "detail" in resp.json()


async def test_a_bad_hex_is_a_schema_422_with_the_usual_shape(client):
    """It was a hand-raised 422 whose `detail` was a string, beside `limit=0`
    on the same route answering with the list every client parses."""
    bad_hex = await client.get("/api/search/color?hex=zz")
    bad_limit = await client.get("/api/search/color?hex=8cb9e1&limit=0")

    assert bad_hex.status_code == 422
    assert isinstance(bad_hex.json()["detail"], list)
    assert isinstance(bad_limit.json()["detail"], list)
    assert (await client.get("/api/search/color?hex=%238cb9e1")).status_code == 200


# ---- typed query parameters -------------------------------------------- #


async def test_an_overlong_search_is_refused_not_a_500(client):
    """A thousand AND-ed terms outgrew SQLite's expression depth: a 500 and an
    `error.unhandled` row from a query string."""
    resp = await client.get("/api/search", params={"q": " ".join(["ab"] * 1000)})

    assert resp.status_code == 422
    rows = (await client.get("/api/admin/activity-log?limit=50")).json()
    assert not any(r["kind"] == "error.unhandled" for r in rows)


async def test_a_capped_search_says_how_many_it_left_out(client, monkeypatch):
    """The search stops at `SEARCH_LIMIT`, and a stop it did not report read
    as the whole answer ("50 of 50" for 55 matches) — dropping the newest."""
    from headroom.services import search_service

    monkeypatch.setattr(search_service, "SEARCH_LIMIT", 2)
    for _ in range(3):
        await client.post(
            "/api/hats",
            json={"condition": "new", "size": "classic", "style": "shore"},
        )

    resp = await client.get("/api/search?q=shore")

    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 2
    assert resp.headers["X-Total-Count"] == "3"


async def test_list_filters_refuse_what_is_not_a_style_or_condition(client):
    """`?style=A-Game` — what the page prints — used to answer 200 with no
    hats, indistinguishable from a real empty result."""
    assert (await client.get("/api/hats?style=A-Game")).status_code == 422
    assert (await client.get("/api/hats?condition=mint")).status_code == 422
    assert (await client.get("/api/hats?style=a_game&condition=new")).status_code == 200


async def test_guest_color_scope_is_typed_too(client, anon_client):
    await client.put("/api/settings/guest-view", json={"enabled": True})

    assert (await anon_client.get("/api/public/guest/collection?color_scope=accent")).status_code == 200
    assert (await anon_client.get("/api/public/guest/collection?color_scope=bogus")).status_code == 422


# ---- the OpenAPI document states what the wire carries ------------------ #


async def test_collection_export_declares_its_zip():
    """It declared a `StreamingResponse` and no content, while returning the
    whole archive from memory."""
    from headroom.app import create_app

    op = create_app().openapi()["paths"]["/api/admin/collection-export"]["get"]
    assert "application/zip" in op["responses"]["200"]["content"]


async def test_hat_read_publishes_its_closed_vocabularies_as_enums():
    """As bare strings the OpenAPI document said nothing, so nothing could hold
    the hand-typed TypeScript unions to the server's values."""
    from headroom.schemas.hat import HatRead

    schema = HatRead.model_json_schema()
    defs = schema.get("$defs", {})

    def _enum(field: str) -> list[str]:
        prop = schema["properties"][field]
        refs = [o["$ref"] for o in prop.get("anyOf", [prop]) if "$ref" in o]
        assert refs, f"{field} is not an enum"
        return defs[refs[0].rsplit("/", 1)[-1]]["enum"]

    assert set(_enum("case_type")) == {"archive", "daily_wear"}
    assert set(_enum("resale_price_scope")) == {"manual", "model", "category"}
    assert set(_enum("analysis_status")) == {"pending", "ok", "fallback", "skipped", "error"}
    assert set(_enum("disposed_via")) == {"sold", "gifted", "lost", "trashed", "trade"}


async def test_statuses_sources_and_timestamps_are_published_as_what_they_are():
    """Job statuses, key sources and task timestamps were bare `str` with the
    values in a comment, or not stated at all."""
    from headroom.schemas.admin import AnalysisJobRead, CatalogStatus, TaskHealthRead
    from headroom.schemas.import_job import ImportJobItemRead, ImportJobRead
    from headroom.schemas.settings import ApiKeyStatus, ModelStatus, TagBaseStatus

    def _values(model, field: str) -> set[str]:
        schema = model.model_json_schema()
        prop = schema["properties"][field]
        options = prop.get("anyOf", [prop])
        found: set[str] = set()
        for o in options:
            if "$ref" in o:
                found |= set(schema["$defs"][o["$ref"].rsplit("/", 1)[-1]]["enum"])
            found |= set(o.get("enum", [])) | ({o["const"]} if "const" in o else set())
        return found

    def _is_timestamp(model, field: str) -> bool:
        prop = model.model_json_schema()["properties"][field]
        return any(o.get("format") == "date-time" for o in prop.get("anyOf", [prop]))

    assert _values(ImportJobRead, "status") == {"queued", "running", "done", "canceled"}
    assert "processing" in _values(ImportJobItemRead, "status")
    assert _values(AnalysisJobRead, "status") == {"running", "done"}
    assert _values(ApiKeyStatus, "source") == {"database", "environment"}
    assert _values(ModelStatus, "source") == {"database", "environment", "default"}
    assert _values(TagBaseStatus, "source") == {"settings", "request"}
    assert _is_timestamp(TaskHealthRead, "last_success_at")
    assert _is_timestamp(TaskHealthRead, "last_attempt_at")
    assert _is_timestamp(CatalogStatus, "last_harvest")


# ---- pydantic's reserved namespace -------------------------------------- #


async def test_no_schema_trips_pydantics_protected_namespace():
    """Import every schema module in a fresh interpreter with warnings as errors.

    The project notes said classes with `model_*` fields opt out of the
    reserved namespace; four of eleven did, and under the pinned pydantic (>= 2.10,
    whose reserved names are only `model_validate`/`model_dump`) the opt-out
    was dead config. Rather than keep a half-applied rule, this checks the
    thing the rule was for: that no schema emits the warning at all. A fresh
    process, because a module already imported in this one would not warn
    again.
    """
    modules = [
        info.name
        for info in pkgutil.walk_packages(schemas_pkg.__path__, schemas_pkg.__name__ + ".")
    ]
    code = "; ".join(f"import {m}" for m in modules)
    result = subprocess.run(
        [sys.executable, "-W", "error::UserWarning", "-c", code],
        capture_output=True, text=True, cwd=_ROOT, timeout=60,
    )
    assert result.returncode == 0, result.stderr[-2000:]
