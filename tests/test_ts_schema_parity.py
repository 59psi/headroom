"""Every TypeScript mirror in `frontend/src/types/index.ts` matches its schema.

`types/index.ts` mirrors the backend's Pydantic schemas, and nothing compared
them: `CatalogStatus.failed_categories` and `RepricingStatus.last_unreachable`
— the two fields that tell a dead harvest or a dead marketplace from a quiet
one — were sent on every request and dropped on the floor by a TS type that
did not declare them, and three fields the server sends as nullable were typed
as always present. Eleven mirrors also went by a second name, so the pairing
could not even be looked up.

This reads the TS interfaces, finds each by NAME among the OpenAPI component
schemas, and holds them to the same fields and the same nullability. A TS
interface with no schema of its own must be a client-side shape and say so
in `CLIENT_ONLY`. (The unions a field spells out are held to the enums by
`test_wire_vocabulary.py`.)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from headroom.app import create_app

pytestmark = pytest.mark.anyio

_TYPES = Path(__file__).resolve().parents[1] / "frontend" / "src" / "types" / "index.ts"

#: TS interfaces with no Pydantic schema, and why.
CLIENT_ONLY: dict[str, str] = {
    "CredentialDescriptorJSON": "inside PasskeyCeremonyOptions.options, which the schema types as an object",
    "CredentialCreationOptionsJSON": "inside PasskeyCeremonyOptions.options",
    "CredentialRequestOptionsJSON": "inside PasskeyCeremonyOptions.options",
    "RegistrationCredentialJSON": "a request body the verify route takes as a free-form object",
    "AuthenticationCredentialJSON": "a request body the verify route takes as a free-form object",
}


def _interfaces() -> dict[str, dict[str, tuple[bool, str]]]:
    """name -> {field: (optional, type text)}, `extends` resolved."""
    src = re.sub(r"/\*[\s\S]*?\*/", "", _TYPES.read_text())
    src = re.sub(r"//[^\n]*", "", src)
    raw: dict[str, tuple[list[str], dict[str, tuple[bool, str]]]] = {}
    for m in re.finditer(r"export interface (\w+)(?:<[^>{]*>)?(?:\s+extends\s+([^{]+))?\s*\{", src):
        depth, i = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(src[i], 0)
            i += 1
        body = src[m.end() : i - 1]
        fields: dict[str, tuple[bool, str]] = {}
        depth, cur = 0, ""
        for ch in body + ";":
            if ch in "{([<":
                depth += 1
            elif ch in "})]>":
                depth -= 1
            if ch in ";\n" and depth == 0:
                fm = re.match(r"^\s*(\w+)(\??)\s*:\s*(.+?)\s*$", cur, re.S)
                if fm:
                    fields[fm.group(1)] = (bool(fm.group(2)), " ".join(fm.group(3).split()))
                cur = ""
                continue
            cur += ch
        parents = [p.strip().split("<")[0] for p in (m.group(2) or "").split(",") if p.strip()]
        raw[m.group(1)] = (parents, fields)

    def resolve(name: str) -> dict[str, tuple[bool, str]]:
        parents, fields = raw[name]
        merged: dict[str, tuple[bool, str]] = {}
        for p in parents:
            if p in raw:
                merged.update(resolve(p))
        merged.update(fields)
        return merged

    return {name: resolve(name) for name in raw}


def _nullable(prop: dict) -> bool:
    return any(alt.get("type") == "null" for alt in prop.get("anyOf", []))


@pytest.fixture(scope="module")
def schemas() -> dict:
    return create_app().openapi()["components"]["schemas"]


async def test_every_ts_interface_names_a_schema_or_says_why_not(schemas):
    orphans = [n for n in _interfaces() if n not in schemas and n not in CLIENT_ONLY]
    assert orphans == [], (
        "TS interfaces with no Pydantic schema of that name (rename to the "
        f"schema's name, or list in CLIENT_ONLY with the reason): {orphans}"
    )


async def test_client_only_entries_are_real():
    stale = [n for n in CLIENT_ONLY if n not in _interfaces()]
    assert stale == [], f"CLIENT_ONLY names interfaces that no longer exist: {stale}"


@pytest.mark.parametrize("name", sorted(n for n in _interfaces() if n not in CLIENT_ONLY))
async def test_a_mirror_has_the_schemas_fields_and_nullability(name, schemas):
    ts = _interfaces()[name]
    schema = schemas[name]
    props = schema.get("properties", {})
    required = set(schema.get("required", []))

    assert set(ts) == set(props), (
        f"{name}: only in TS {sorted(set(ts) - set(props))}, "
        f"only in the schema {sorted(set(props) - set(ts))}"
    )
    wrong = []
    for field, (optional, ts_type) in ts.items():
        ts_null = bool(re.search(r"\bnull\b", ts_type))
        if ts_null != _nullable(props[field]):
            wrong.append(f"{field}: TS `{ts_type}`, schema nullable={_nullable(props[field])}")
        if optional and field in required:
            wrong.append(f"{field}: optional in TS, required by the schema")
    assert wrong == [], f"{name}: " + "; ".join(wrong)
