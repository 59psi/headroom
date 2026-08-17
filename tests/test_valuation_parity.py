"""Keep the server's valuation constants equal to the browser's.

The rule is stated once, in `frontend/src/lib/valuation.ts`, because every
screen that shows a value is React. The server needs the same rule for one
thing only — the printable inventory report, which is rendered server-side and
cannot import TypeScript — so `services/valuation.py` restates it.

Restating is how this whole area went wrong in the first place: three
hand-written copies of the resale calculation drifted until the home page was
describing multipliers that were no longer being applied to most of the
collection, and the number on screen looked exactly as confident as before.
Nobody can eyeball whether a collection total is right, so nothing catches it.

These assertions read the real constants out of the TypeScript source and
compare them to the Python ones. Editing one side alone fails here rather than
silently issuing an insurance document that disagrees with the app.
"""

import re
from pathlib import Path

import pytest

from headroom.services import valuation

pytestmark = pytest.mark.anyio

_ROOT = Path(__file__).resolve().parents[1]
_TS = _ROOT / "frontend/src/lib/valuation.ts"


def _ts_source() -> str:
    assert _TS.exists(), f"{_TS} is missing — it owns the valuation rule"
    return _TS.read_text()


def _ts_number(name: str) -> float:
    """Read `export const NAME = 0.85;` out of the TypeScript module."""
    match = re.search(rf"export const {name} = ([0-9.]+);", _ts_source())
    assert match, f"{name} is no longer a plain exported number in {_TS.name}"
    return float(match.group(1))


def _ts_table(name: str) -> dict[str, float]:
    """Read `export const NAME: Record<string, number> = {...}` into a dict."""
    match = re.search(
        rf"export const {name}: Record<string, number> = \{{(.*?)\}};",
        _ts_source(),
        re.DOTALL,
    )
    assert match, f"{name} is no longer an exported Record literal in {_TS.name}"
    return {
        key: float(value)
        for key, value in re.findall(r"(\w+):\s*([0-9.]+)", match.group(1))
    }


async def test_ask_to_sold_discount_matches():
    assert valuation.ASK_TO_SOLD == _ts_number("ASK_TO_SOLD")


async def test_condition_vs_market_table_matches():
    assert valuation.CONDITION_VS_MARKET == _ts_table("CONDITION_VS_MARKET")


async def test_retail_retention_table_matches():
    assert valuation.RETAIL_RETENTION == _ts_table("RETAIL_RETENTION")


async def test_basis_labels_match():
    """The report prints these strings, so a rename must reach both sides."""
    labels = dict(
        re.findall(r"(\w+):\s*'([^']+)'", re.search(
            r"export const BASIS_LABEL: Record<ValueBasis, string> = \{(.*?)\};",
            _ts_source(),
            re.DOTALL,
        ).group(1))
    )
    assert valuation.BASIS_LABEL == labels


async def test_the_python_rule_ranks_signals_the_same_way():
    """A short behavioural check, not just constant equality.

    Constants matching wouldn't catch the branches being ordered differently —
    which is precisely the bug the report had, preferring an undiscounted eBay
    ask over everything else.
    """
    from headroom.models.hat import Hat

    def hat(**kw) -> Hat:
        return Hat(condition=kw.pop("condition", "new"), size="classic",
                   style="a_game", **kw)

    manual = valuation.value_hat(
        hat(resale_price=250.0, resale_price_scope="manual", condition="worn")
    )
    assert manual.basis == "manual"
    assert manual.value == 250.0  # never discounted

    comp = valuation.value_hat(
        hat(resale_price=100.0, resale_price_scope="model", condition="worn")
    )
    assert comp.basis == "comp"
    assert comp.value < 100.0  # an ask is not a sale price

    # Retail beats a category median, because retail is about THIS hat while a
    # category median is the going rate for every hat of that shape.
    mixed = valuation.value_hat(
        hat(estimated_new_price=200.0, resale_price=900.0,
            resale_price_scope="category", condition="new")
    )
    assert mixed.basis == "retail"
    assert mixed.value == pytest.approx(200.0 * valuation.RETAIL_RETENTION["new"])

    unpriced = valuation.value_hat(hat())
    assert unpriced.basis == "none"
    assert unpriced.value is None  # not 0.0
