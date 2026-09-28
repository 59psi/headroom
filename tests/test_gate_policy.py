"""The gate's own tuples, and the one cross-origin grant the app can make.

`tests/test_security.py` enumerates the route table against the gate from the
outside. These pin the two things that enumeration cannot see: that each
exemption in `auth._OPEN_PREFIXES` actually exempts something, and that CORS —
a grant of credentialed access to someone else's pages — exists only when an
operator asked for it.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def test_every_open_prefix_carves_something_out_of_the_protected_set():
    """An exemption for a path the gate never covered exempts nothing.

    `/health` sat in `_OPEN_PREFIXES` for releases. No protected prefix
    matches it, so deleting it changed nothing and the full suite stayed
    green — but in the one tuple that defines what is open, a do-nothing
    entry reads as policy, and the next editor reasons from it. Every entry
    must begin with a protected prefix, or it is not an exemption.
    """
    from headroom import auth

    dead = [
        open_prefix for open_prefix in auth._OPEN_PREFIXES
        if not open_prefix.startswith(auth._PROTECTED_PREFIXES)
    ]
    assert dead == [], f"open prefixes outside the protected set exempt nothing: {dead}"


@pytest.mark.parametrize("path", ["/health", "/health/ready"])
async def test_the_health_probes_are_open_because_nothing_protects_them(anon_client, path):
    """Open by being outside `_PROTECTED_PREFIXES`, not by an exemption."""
    resp = await anon_client.get(path)
    assert resp.status_code != 401, f"{path} demanded a login from the container check"
    assert resp.status_code < 500, resp.text


def _cors_headers(resp) -> dict[str, str]:
    return {k: v for k, v in resp.headers.items() if k.lower().startswith("access-control-")}


async def test_no_configured_origin_means_no_cors_at_all(monkeypatch):
    """No `HEADROOM_CORS_ORIGINS`, no CORS middleware, no CORS headers.

    The SPA is same-origin in production and, through Vite's proxy, in
    development too; nothing the project ships needs a cross-origin read. Left
    installed with an empty list, the middleware still stamped
    `Access-Control-Allow-Credentials: true` on every response to a request
    carrying an `Origin` — a credential grant with no origin behind it.
    """
    from httpx import ASGITransport, AsyncClient

    from headroom.app import create_app
    from headroom.config import settings

    monkeypatch.setattr(settings, "cors_origins", [])
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        simple = await c.get("/health", headers={"Origin": "http://localhost:5173"})
        preflight = await c.options(
            "/api/auth/status",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert _cors_headers(simple) == {}, _cors_headers(simple)
    assert _cors_headers(preflight) == {}, _cors_headers(preflight)


async def test_an_unconfigured_install_names_no_cors_origin(monkeypatch):
    """The test above sets the list empty by hand; this is the default itself.

    It used to be the Vite dev server's `http://localhost:5173`, so the
    "opt-in" middleware was installed on every install that never opted in —
    a credentialed grant to an origin the dev SPA does not even use (it goes
    through Vite's proxy, same-origin).
    """
    from headroom import config

    monkeypatch.delenv("HEADROOM_CORS_ORIGINS", raising=False)
    assert config.Settings().cors_origins == []


async def test_a_configured_origin_gets_credentialed_cors_and_no_other_does(monkeypatch):
    """Opt-in still works: the one origin named gets a credentialed grant."""
    from httpx import ASGITransport, AsyncClient

    from headroom.app import create_app
    from headroom.config import settings

    allowed = "https://headroom.example"
    monkeypatch.setattr(settings, "cors_origins", [allowed])
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ok = await c.get("/health", headers={"Origin": allowed})
        other = await c.get("/health", headers={"Origin": "http://localhost:5173"})

    assert ok.headers.get("access-control-allow-origin") == allowed
    assert ok.headers.get("access-control-allow-credentials") == "true"
    assert "access-control-allow-origin" not in other.headers
