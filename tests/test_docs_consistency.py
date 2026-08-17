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


async def test_pricing_prompt_keeps_its_anchors():
    """The price prompt must stay anchored on real numbers.

    Without anchors Claude priced melin hats at roughly half of actual — an
    unanchored "use your knowledge of typical pricing tiers" is exactly the
    wording that produced it. This does not check that the prices are still
    *current* (a test cannot know that), only that the anchors are still there
    and that HYDROLite is still described as the premium tier — the one place
    where a flag the app already tracks should push the estimate up.
    """
    from headroom.services.claude_analysis import SYSTEM_PROMPT

    assert "PRICING" in SYSTEM_PROMPT
    for anchor in ("$69", "$79", "$89", "$99"):
        assert anchor in SYSTEM_PROMPT, f"lost the {anchor} price anchor"

    # Construction, not model line, is what moves the price.
    assert "HYDROLite" in SYSTEM_PROMPT
    assert "ABOVE a plain HYDRO" in SYSTEM_PROMPT, (
        "HYDROLite must still be described as pricier than HYDRO — the hydrolite"
        " flag is otherwise a signal the estimate ignores"
    )
    # The exact phrasing that caused the underestimate must not come back.
    assert "using your knowledge of\n     the brand's typical pricing tiers" not in SYSTEM_PROMPT
