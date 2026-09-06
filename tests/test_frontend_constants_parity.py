"""Server constants the frontend restates, pinned to the Python that owns them.

Same mechanism as `test_valuation_parity` and `test_capacity_parity`: read the
value out of the TypeScript source and compare it with the module that decides
it. Each of these was a hand-typed copy with a comment asking to be kept in
step ("must match the `STAGE_*` constants…", "Mirrors `HAT_DEFAULTS`…") and
nothing checking that it was — the shape the capacity figure took three
release cycles to get a guard for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from headroom.schemas.hat import HAT_DEFAULTS
from headroom.schemas.share import DEFAULT_SHARE_EXPIRY_DAYS
from headroom.services import hat_analysis_pipeline, import_service

pytestmark = pytest.mark.anyio

_ROOT = Path(__file__).resolve().parents[1]
_FRONTEND = _ROOT / "frontend" / "src"


def _read(rel: str) -> str:
    return (_FRONTEND / rel).read_text()


async def test_the_pipeline_stages_and_their_order():
    """`AnalysisStatus.STAGES` — position IS the rendered step number."""
    src = _read("components/hats/AnalysisStatus.tsx")
    m = re.search(r"export const STAGES = \[([^\]]+)\] as const;", src)
    assert m, "STAGES not found"
    ts_stages = re.findall(r"'([^']+)'", m.group(1))
    py_stages = [
        hat_analysis_pipeline.STAGE_CUTOUT,
        hat_analysis_pipeline.STAGE_IDENTIFYING,
        hat_analysis_pipeline.STAGE_PRICING,
        hat_analysis_pipeline.STAGE_RESALE,
    ]
    assert ts_stages == py_stages, f"TS {ts_stages} vs Python {py_stages}"


async def test_the_add_form_defaults_are_the_import_defaults():
    """`DEFAULT_HAT_BASICS` mirrors `HAT_DEFAULTS`; the share-target card and
    the Add page both read the TS copy, so it is the one that has to agree."""
    src = _read("components/hats/HatFormFields.tsx")
    block = re.search(r"export const DEFAULT_HAT_BASICS[^=]*= \{([^}]+)\}", src, re.S)
    assert block, "DEFAULT_HAT_BASICS not found"
    ts = dict(re.findall(r"(\w+): '([^']*)'", block.group(1)))
    for key in ("style", "size", "condition"):
        assert ts[key] == HAT_DEFAULTS[key], f"{key}: TS {ts[key]!r} vs HAT_DEFAULTS {HAT_DEFAULTS[key]!r}"


async def test_the_bulk_import_file_cap():
    src = _read("pages/BulkImportPage.tsx")
    m = re.search(r"^const MAX_FILES = (\d+);", src, re.M)
    assert m, "MAX_FILES not found"
    assert int(m.group(1)) == import_service.MAX_FILES_PER_JOB


async def test_the_share_link_expiry_default():
    """The card seeds its selector with the server default so the two agree on
    what "not choosing" means. `useState('30')` was the copy."""
    src = _read("components/settings/ShareLinksCard.tsx")
    m = re.search(r"useState\('(\d+)'\)", src)
    assert m, "expiry seed not found"
    assert int(m.group(1)) == DEFAULT_SHARE_EXPIRY_DAYS
