"""Nothing in the published tree points at a file the published tree lacks.

The contributor notes, the review write-ups and the audit record are
local-only and gitignored, so a fresh clone has none of them. A comment that
says "see <one of those files>" is a dangling pointer to every reader of the
public repo — and the audit record's finding numbers, quoted beside it, index
a security register the repository deliberately stopped publishing.

A sweep removed thirty-nine such citations, and the same round added two new
ones in files it created. A grep at fix time holds for one commit; this holds
for every later one. The rule itself is stated in the file instead: say the
rule, or name the test or public doc that enforces it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).resolve().parents[1]

# Spelled in pieces so this file does not trip its own scan.
_PRIVATE = re.compile("|".join(
    re.escape(name) for name in ("CLAUDE" + ".md", "AUDIT" + "-HISTORY", "CODE" + "-REVIEW-")
))

#: Where published prose lives: code comments, tests, scripts, docs, config.
_SCANNED_DIRS = ("src", "tests", "scripts", "docs", ".github", "frontend/src")
_SCANNED_FILES = (
    "README.md",
    "Dockerfile",
    "pyproject.toml",
    "frontend/package.json",
    "frontend/vite.config.ts",
    "frontend/.oxlintrc.json",
    "frontend/index.html",
)
_SKIPPED_PARTS = {"node_modules", "dist", "__pycache__", ".venv"}

#: Files that name the private ones ON PURPOSE: the ignore lists that keep
#: them out of the repository and the image, and the release note that says
#: they left. The private files themselves are in a working tree but never
#: in a clone.
_ALLOWED = {".gitignore", ".dockerignore", "CHANGELOG.md"}


def _is_private_file(path: Path) -> bool:
    """One of the local-only files itself (present in a working tree only)."""
    rel = path.relative_to(ROOT).as_posix()
    return rel == "CLAUDE" + ".md" or (
        rel.startswith("docs/") and "/" not in rel[5:]
        and _PRIVATE.match(path.name) is not None and path.suffix == ".md"
    )


def _published_files():
    for name in _SCANNED_FILES:
        path = ROOT / name
        if path.is_file():
            yield path
    for top in _SCANNED_DIRS:
        base = ROOT / top
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or _SKIPPED_PARTS & set(path.parts):
                continue
            if path.name in _ALLOWED or _is_private_file(path):
                continue
            yield path


async def test_no_published_file_cites_a_local_only_one():
    hits = []
    for path in _published_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary assets: fonts, icons, images
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _PRIVATE.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()[:100]}")
    assert hits == [], (
        "cites a gitignored, local-only file — state the rule instead, or name "
        "the test or public doc that enforces it:\n  " + "\n  ".join(hits)
    )


async def test_the_scan_sees_what_it_is_meant_to():
    """A scan that silently read nothing would pass forever."""
    scanned = {p.relative_to(ROOT).as_posix() for p in _published_files()}

    assert "src/headroom/app.py" in scanned
    assert "frontend/src/lib/invalidate.ts" in scanned
    assert "frontend/.oxlintrc.json" in scanned
    assert not any(_is_private_file(ROOT / p) for p in scanned)
