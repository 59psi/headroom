"""The closed vocabularies on the wire, held to the code that owns them.

Read schemas published these as bare `str` — `case_type`, `resale_price_scope`,
`disposed_via`, the job statuses — while `frontend/src/types/index.ts` restated
each as a hand-typed union, and nothing compared the two. They are enums now,
so the OpenAPI document states them; this compares every union the TypeScript
spells out against the enum, and the enums against the service constants that
write the values. A TS field typed plain `string` is left alone — it cannot
disagree, only be vague — but a union that names values must name these.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

import pytest

from headroom.models.hat import ResaleScope
from headroom.schemas.admin import AnalysisJobStatus
from headroom.schemas.case import CaseType
from headroom.schemas.hat import AnalysisStage, AnalysisStatus, ColorTier, DisposedVia
from headroom.schemas.import_job import ImportItemStatus, ImportJobStatus

pytestmark = pytest.mark.anyio

_TYPES = Path(__file__).resolve().parents[1] / "frontend" / "src" / "types" / "index.ts"

#: (TS interface, field, the enum it must match).
_UNIONS: list[tuple[str, str, type[StrEnum]]] = [
    ("CaseRead", "case_type", CaseType),
    ("HatRead", "case_type", CaseType),
    ("HatRead", "resale_price_scope", ResaleScope),
    ("HatRead", "analysis_status", AnalysisStatus),
    ("HatRead", "analysis_stage", AnalysisStage),
    ("HatRead", "disposed_via", DisposedVia),
    ("ColorTag", "tier", ColorTier),
    ("ImportJobItemRead", "status", ImportItemStatus),
    ("ImportJobRead", "status", ImportJobStatus),
    ("AnalysisJobRead", "status", AnalysisJobStatus),
    ("AnalysisJobHat", "analysis_status", AnalysisStatus),
]


def _ts_field(interface: str, field: str) -> str:
    src = _TYPES.read_text()
    block = re.search(rf"export interface {interface}\b[^{{]*\{{(.*?)\n\}}", src, re.S)
    assert block, f"interface {interface} not found in types/index.ts"
    line = re.search(rf"^\s*{field}\??:\s*([^;]+);", block.group(1), re.M)
    assert line, f"{interface}.{field} not found"
    return line.group(1)


@pytest.mark.parametrize(("interface", "field", "enum"), _UNIONS)
async def test_a_typescript_union_names_exactly_the_servers_values(interface, field, enum):
    ts = _ts_field(interface, field)
    literals = set(re.findall(r"'([^']*)'", ts))
    if not literals:
        pytest.skip(f"{interface}.{field} is typed `{ts.strip()}` — nothing to drift")
    assert literals == {e.value for e in enum}, f"{interface}.{field}: TS {sorted(literals)}"


async def test_the_stage_vocabulary_is_the_pipelines():
    from headroom.services import hat_analysis_pipeline as p

    assert {e.value for e in AnalysisStage} == {
        p.STAGE_CUTOUT, p.STAGE_IDENTIFYING, p.STAGE_PRICING, p.STAGE_RESALE,
    }


async def test_the_status_vocabularies_cover_what_the_services_write():
    from headroom.services import analysis_job_service, analysis_queue, import_service

    assert {analysis_job_service.RUNNING, analysis_job_service.DONE} == {
        e.value for e in AnalysisJobStatus
    }
    assert analysis_queue.PENDING == AnalysisStatus.pending
    assert set(import_service._JOB_COUNTER) <= {e.value for e in ImportItemStatus}


async def test_the_color_tiers_are_the_analyzers():
    """The manual-edit path now refuses a tier outside this set; it must be the
    same set the Claude tool schema asks for."""
    from headroom.services import claude_analysis

    src = Path(claude_analysis.__file__).read_text()
    tier_enum = re.search(r'"tier":\s*\{[^}]*"enum":\s*\[([^\]]+)\]', src, re.S)
    assert tier_enum, "tier enum not found in the Claude tool schema"
    assert set(re.findall(r'"([^"]+)"', tier_enum.group(1))) == {e.value for e in ColorTier}
