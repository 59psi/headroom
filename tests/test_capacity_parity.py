"""Keep the UI's stated default capacities equal to the enforced ones.

`services/capacity.py` is the authority: it decides what a case accepts and
publishes the per-case numbers the pickers render. The one number no
particular case can report is the DEFAULT, shown as a placeholder on the
create and edit forms — and that was typed by hand, in two files, reading
"Default: 4 regular / 6 beanies". Wrong in both digits, in a codebase whose
own physical article is a three-hat travel case.

Nobody proof-reads a placeholder. `test_valuation_parity.py` exists because
the same class of mistake had already happened once with the valuation
constants; this is the same mechanism applied to the second one.
"""

import re
from pathlib import Path

import pytest

from headroom.services import capacity

pytestmark = pytest.mark.anyio

_ROOT = Path(__file__).resolve().parents[1]
_TS = _ROOT / "frontend/src/lib/capacity.ts"


def _ts_number(name: str) -> int:
    assert _TS.exists(), f"{_TS} is missing — it owns the UI's stated defaults"
    match = re.search(rf"export const {name} = (\d+);", _TS.read_text())
    assert match, f"{name} is no longer a plain exported number in {_TS.name}"
    return int(match.group(1))


async def test_the_regular_default_matches():
    assert _ts_number("DEFAULT_REGULAR_CAPACITY") == capacity.MAX_REGULAR


async def test_the_beanie_default_matches():
    assert _ts_number("DEFAULT_BEANIE_CAPACITY") == capacity.MAX_BEANIE


async def test_the_overfill_allowances_match():
    """The squeeze is part of what the placeholder promises, so pin it too.

    A regular case is nominally 3 and takes a 4th; a beanie case is 8 and
    takes no more. Getting these wrong would make the form's "(4 at a
    squeeze)" a lie the moment either side moved.
    """
    assert _ts_number("REGULAR_OVERFILL_ALLOWANCE") == capacity.OVERFILL_ALLOWANCE
    assert _ts_number("BEANIE_OVERFILL_ALLOWANCE") == capacity.BEANIE_OVERFILL_ALLOWANCE


async def test_the_placeholder_is_built_and_not_typed():
    """The digits must come from the constants, or this test proves nothing.

    A hand-written string would keep passing the two assertions above while
    still showing the wrong numbers — which is exactly the state this file
    was written to end.
    """
    source = _TS.read_text()
    placeholder = re.search(r"CAPACITY_PLACEHOLDER =\s*(.+?);", source, re.S)

    assert placeholder, "CAPACITY_PLACEHOLDER is missing"
    assert "${DEFAULT_REGULAR_CAPACITY}" in placeholder.group(1)
    assert "${DEFAULT_BEANIE_CAPACITY}" in placeholder.group(1)


async def test_no_page_hardcodes_a_capacity_placeholder():
    """Both case forms had their own copy. Neither may grow one back."""
    pages = (_ROOT / "frontend/src/pages").glob("*.tsx")
    offenders = [
        p.name for p in pages
        if re.search(r'placeholder="Default: \d+ regular', p.read_text())
    ]

    assert not offenders, f"hard-coded capacity placeholder in {offenders}"
