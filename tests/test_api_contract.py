"""Every JSON response this API returns has a declared shape.

CLAUDE.md states one convention outright — "no schema is declared inline in a
route" — and the schema modules' own docstrings describe the failure it
prevents: a hand-built dict is a response nobody can type a client against,
and `frontend/src/types/index.ts` mirrors "backend Pydantic schemas", so a
dict has nothing to mirror. Eleven endpoints returned bare dicts at 2.77.3,
including the one that writes purchase prices onto hats. This enumerates the
OpenAPI document the way `test_security` does for the auth gate, so the next
`return {...}` fails here instead of surviving until a review reads the route.
"""

from __future__ import annotations

import pytest

from headroom.app import create_app

pytestmark = pytest.mark.anyio

def _json_schema(response: dict) -> dict | None:
    content = response.get("content") or {}
    body = content.get("application/json")
    if body is None:
        return None
    return body.get("schema")


def _is_declared(schema: dict | None) -> bool:
    """A `$ref` to a component, an array of refs, or a typed primitive/array.

    FastAPI emits `{}` (any) for a route with no `response_model` whose handler
    returns a dict — that is the undeclared shape this test exists to catch.
    """
    if not schema:
        return False
    if "$ref" in schema or "anyOf" in schema or "oneOf" in schema:
        return True
    if schema.get("type") == "array":
        return _is_declared(schema.get("items"))
    return schema.get("type") in {"string", "integer", "number", "boolean"}


async def test_every_json_response_has_a_declared_schema():
    spec = create_app().openapi()
    undeclared: list[str] = []
    for path, operations in spec["paths"].items():
        for method, op in operations.items():
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            for status, response in (op.get("responses") or {}).items():
                if not status.startswith("2") or status == "204":
                    continue
                content = response.get("content") or {}
                if not content:
                    continue  # a bare 2xx with no body (e.g. a redirect)
                if "application/json" not in content:
                    continue  # file/stream/HTML responses declare their own media type
                if not _is_declared(_json_schema(response)):
                    undeclared.append(f"{method.upper()} {path} -> {status}")
    assert undeclared == [], (
        "JSON responses with no declared schema (hand-built dicts):\n  "
        + "\n  ".join(undeclared)
    )
