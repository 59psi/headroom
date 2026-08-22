"""Pin the places that restate the default Claude model to the code that owns it.

`config.Settings.anthropic_model` is the single source of truth, but three other
files quote it to a human: the README env table, the OPERATIONS env table, and
the Settings UI, which labels one option "(default)". Nothing links them, so a
model bump can update the code and leave all three advertising the old id —
which is exactly how the app spent a generation pointing users at a superseded
model while every test stayed green.

These assertions are cheap and catch that at PR time instead of in a doc audit.
"""

import re
from pathlib import Path

import pytest

from headroom.config import settings

pytestmark = pytest.mark.anyio

_ROOT = Path(__file__).resolve().parents[1]
_MODEL_CARD = _ROOT / "frontend/src/components/settings/ClaudeModelCard.tsx"

# `| `HEADROOM_ANTHROPIC_MODEL` | `claude-…` | …` — grab the second column.
_ENV_ROW = re.compile(r"\|\s*`HEADROOM_ANTHROPIC_MODEL`\s*\|\s*`([^`]+)`")
# `{ id: 'claude-…', label: '… (default)' },`
_DEFAULT_OPTION = re.compile(r"id:\s*'([^']+)',\s*label:\s*'[^']*\(default\)")


@pytest.mark.parametrize("doc", ["README.md", "docs/OPERATIONS.md"])
async def test_docs_advertise_the_real_default_model(doc):
    match = _ENV_ROW.search((_ROOT / doc).read_text())
    assert match, f"{doc} no longer has a HEADROOM_ANTHROPIC_MODEL row to check"
    assert match.group(1) == settings.anthropic_model, (
        f"{doc} advertises '{match.group(1)}' but the code default is "
        f"'{settings.anthropic_model}'"
    )


async def test_settings_ui_marks_the_real_default_model():
    source = _MODEL_CARD.read_text()
    match = _DEFAULT_OPTION.search(source)
    assert match, "no model option in ClaudeModelCard.tsx is labelled '(default)'"
    assert match.group(1) == settings.anthropic_model, (
        f"the Settings picker labels '{match.group(1)}' as the default but the "
        f"code default is '{settings.anthropic_model}'"
    )


async def test_settings_ui_offers_the_default_model_as_a_choice():
    """The default must be selectable, not only reachable via "Other…"."""
    ids = set(re.findall(r"id:\s*'(claude-[^']+)'", _MODEL_CARD.read_text()))
    assert settings.anthropic_model in ids, (
        f"'{settings.anthropic_model}' is the default but isn't in the picker's "
        f"model list: {sorted(ids)}"
    )


async def test_the_prompt_agrees_with_the_price_table():
    """The prompt must not restate prices that the table now owns.

    This test used to assert the prompt still contained "$69" — enshrining a
    stale anchor as a requirement. That was the wrong thing to pin twice over:
    the numbers had drifted years out of date, and the prompt was the wrong
    place for them at all. A photo cannot show a price, so those anchors WERE
    the answer, which meant the whole collection was priced by a comment.

    `retail_pricing` owns melin prices now and OVERRIDES the model. What still
    matters is that the two do not contradict each other — a prompt that told
    Claude a HYDRO was $69 while the table said $79 would produce estimates the
    table then silently discarded, which is just a slower way to be wrong.
    """
    from headroom.services.claude_analysis import SYSTEM_PROMPT
    from headroom.services import retail_pricing

    assert "PRICING" in SYSTEM_PROMPT

    # Every price the prompt quotes for a construction the table knows must be
    # the table's number.
    hydro = retail_pricing.base_retail("a_game", "HYDRO")
    lite = retail_pricing.base_retail("a_game", "HYDROLite")
    assert f"HYDRO ${hydro:.0f}" in SYSTEM_PROMPT, (
        f"prompt disagrees with the table on HYDRO (${hydro:.0f})"
    )
    assert f"HYDROLite ${lite:.0f}" in SYSTEM_PROMPT, (
        f"prompt disagrees with the table on HYDROLite (${lite:.0f})"
    )

    # The stale anchor must not come back, in the prompt or anywhere near it.
    assert "$69 is the common price" not in SYSTEM_PROMPT

    # The prompt's remaining job is the EXCEPTIONS — the cases the table cannot
    # see. If that framing is lost, the estimate becomes noise the table drops.
    assert "HIGHER than the base" in SYSTEM_PROMPT
    # The exact phrasing that caused the original underestimate must not return.
    assert "using your knowledge of\n     the brand's typical pricing tiers" not in SYSTEM_PROMPT
