"""The email-import prompt must name the fields the importer actually reads.

The Purchase History card ships a copyable prompt that asks Claude/ChatGPT to
turn a mailbox into importable JSON. It is a SCHEMA STATED IN PROSE, sitting in
a TSX file, describing a Python parser — three things free to drift apart with
nothing connecting them.

The failure is silent and expensive: a prompt naming a field the importer
ignores produces JSON that imports "successfully" with that data quietly
dropped. `purchased_at` instead of `order_date` loses every order date, the
import reports success, and nothing anywhere says a field was discarded. It was
`purchased_at` in the first draft of this feature, caught only by reading the
parser.

So: every field the prompt promises must be one `catalog_service` reads, and
the required one must be the one the parser requires.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.anyio

CARD = (
    Path(__file__).resolve().parents[1]
    / "frontend/src/components/settings/PurchasesCard.tsx"
)
SERVICE = (
    Path(__file__).resolve().parents[1]
    / "src/headroom/services/catalog_service.py"
)


def _prompt_text() -> str:
    source = CARD.read_text()
    match = re.search(
        r"const EMAIL_IMPORT_PROMPT = `(.*?)`;", source, re.DOTALL
    )
    assert match, "EMAIL_IMPORT_PROMPT not found — did the constant get renamed?"
    return match.group(1)


def _fields_the_prompt_promises(prompt: str) -> set[str]:
    """Field names from the prompt's field list.

    The list is two-space-indented `name  description` lines; anything else in
    the prompt is prose. Parsed rather than hardcoded so editing the prompt is
    what this test sees.
    """
    fields = set()
    for line in prompt.splitlines():
        m = re.match(r"^  ([a-z][a-z0-9_]*)\s{2,}\S", line)
        if m:
            fields.add(m.group(1))
    assert fields, "parsed no fields out of the prompt — has its shape changed?"
    return fields


def _fields_the_importer_reads() -> set[str]:
    """Every key `catalog_service` pulls off an incoming line item."""
    source = SERVICE.read_text()
    return set(re.findall(r"""item\.get\(\s*["']([a-z_]+)["']""", source))


async def test_every_promised_field_is_one_the_importer_reads():
    promised = _fields_the_prompt_promises(_prompt_text())
    read = _fields_the_importer_reads()

    unknown = promised - read
    assert not unknown, (
        f"the prompt promises {sorted(unknown)}, which the importer never reads. "
        f"JSON built from it would import with those values silently dropped. "
        f"Fields actually read: {sorted(read)}"
    )


async def test_the_prompt_names_the_date_field_the_parser_parses():
    """Pinned by name because this is the one that was wrong.

    `order_date` is parsed with `datetime.fromisoformat`; `purchased_at` is a
    plausible-looking name that no code path reads.
    """
    prompt = _prompt_text()
    assert "order_date" in prompt
    assert "purchased_at" not in prompt


async def test_the_prompt_requires_the_field_the_importer_requires():
    """`item_title` is the only field without which a line cannot be imported —
    `_line_fields` derives model and colorway from it and an empty title is
    skipped. The prompt must mark exactly that one required."""
    prompt = _prompt_text()
    assert re.search(r"item_title\s+\(required\)", prompt), (
        "item_title must be marked required in the prompt"
    )
    # And nothing else should claim to be required: every other field is
    # optional in the parser, and over-claiming makes the assistant invent
    # values for receipts that do not show them.
    required = set(re.findall(r"^  ([a-z_]+)\s+\(required\)", prompt, re.M))
    assert required == {"item_title"}, required


async def test_the_prompt_preserves_what_dedupe_depends_on():
    """The dedupe key is (order_ref, item_title, price, size).

    An assistant told to tidy up duplicate lines would collapse genuinely
    separate purchases — one real order bought the same model in Classic x2 and
    Small x1 — so the prompt has to name those fields AND forbid merging.
    """
    prompt = _prompt_text()
    for field in ("order_ref", "price", "size"):
        assert field in prompt, field
    assert re.search(r"do not merge|not merge", prompt, re.I), prompt
