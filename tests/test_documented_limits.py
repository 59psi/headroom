"""The limits USAGE.md promises, pinned to the code that enforces them.

"Photos are capped at 20 MB each; a bulk import batch at 750 MB and 100
files" and "(90 days by default)" were each a sentence with nothing behind
it: raising the photo cap to 25 MB, the batch cap to 800 MB or the retention
to 91 days left the whole suite green. The numbers are read out of the
document rather than restated here, so the guard fails whichever side moves.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from headroom.services import activity_service, import_service
from headroom.utils import upload

pytestmark = pytest.mark.anyio

_USAGE = (Path(__file__).resolve().parents[1] / "docs" / "USAGE.md").read_text()
_MB = 1024 * 1024


def _caps() -> tuple[int, int, int]:
    m = re.search(
        r"Photos are capped at (\d+) MB each; a bulk import batch at (\d+) MB and (\d+)\s+files",
        _USAGE,
    )
    assert m, "USAGE.md no longer states the upload caps in the sentence this test reads"
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


async def test_the_documented_photo_cap_is_the_enforced_one():
    photo_mb, _, _ = _caps()
    assert upload.MAX_PHOTO_BYTES == photo_mb * _MB


async def test_bulk_import_enforces_the_same_per_photo_cap():
    """One number, not two 20 MBs that happen to agree today."""
    assert import_service.MAX_BYTES_PER_FILE == upload.MAX_PHOTO_BYTES


async def test_the_documented_batch_caps_are_the_enforced_ones():
    _, batch_mb, batch_files = _caps()
    assert import_service.MAX_TOTAL_UPLOAD_BYTES == batch_mb * _MB
    assert import_service.MAX_FILES_PER_JOB == batch_files


async def test_the_documented_retention_is_the_default(monkeypatch):
    m = re.search(r"retention\s+window \((\d+) days by default\)", _USAGE)
    assert m, "USAGE.md no longer states the audit-log retention default"
    monkeypatch.delenv("HEADROOM_ACTIVITY_LOG_RETENTION_DAYS", raising=False)
    assert activity_service.retention_days() == int(m.group(1))
