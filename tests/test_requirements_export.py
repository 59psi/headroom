"""`requirements.txt` must not drift from `uv.lock`.

The Docker build installs dependencies from `requirements.txt` rather than from
`pyproject.toml`, because that file carries the project VERSION and so busts
the dependency layer on every release — measured at 490s of an 873s rebuild on
the Pi this deploys to.

The cost of that trick is a second file describing the same thing, and the
failure mode is silent: a dependency bump lands in `uv.lock`, `requirements.txt`
is not regenerated, and the image quietly keeps installing the OLD set while
every test passes against the new one. This test is the whole reason that
trade is acceptable.

Regenerate with:

    uv export --frozen --no-dev --no-emit-project \\
        --format requirements-txt -o requirements.txt
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"

EXPORT_CMD = [
    "uv", "export", "--frozen", "--no-dev", "--no-emit-project",
    "--format", "requirements-txt",
]


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _significant(text: str) -> list[str]:
    """Just the pins, with comments and terminal color removed.

    Two things differ between the committed file and a fresh export that say
    nothing about which packages are installed: `uv export` records its own
    command line in a header comment (so `-o requirements.txt` differs from
    stdout), and it colorizes annotations when writing to a stream but not to
    a file. Comparing either would fail this test for a reason that cannot
    reach the image.
    """
    out = []
    for raw in text.splitlines():
        line = _ANSI.sub("", raw).rstrip()
        if line.strip() and not line.lstrip().startswith("#"):
            out.append(line)
    return out


def _copy_targets(dockerfile: str) -> list[str]:
    """The COPY directives, in order — not every mention of one.

    Matching raw text found this file's own explanatory comments before the
    instructions they describe.
    """
    return [
        line.strip()
        for line in dockerfile.splitlines()
        if line.strip().startswith("COPY ")
    ]


async def test_requirements_txt_matches_the_lockfile():
    assert REQUIREMENTS.is_file(), (
        "requirements.txt is missing — the Docker build installs from it. "
        f"Regenerate: {' '.join(EXPORT_CMD)} -o requirements.txt"
    )

    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        EXPORT_CMD, cwd=ROOT, capture_output=True, text=True, check=False,
        env={**os.environ, "NO_COLOR": "1"},
    )
    if result.returncode != 0:
        pytest.skip(f"uv export unavailable here: {result.stderr[:200]}")

    assert _significant(result.stdout) == _significant(REQUIREMENTS.read_text()), (
        "requirements.txt is out of date with uv.lock. The image would install "
        "a different dependency set than the tests just ran against. "
        f"Regenerate: {' '.join(EXPORT_CMD)} -o requirements.txt"
    )


async def test_the_export_is_hash_pinned():
    """`--require-hashes` in the Dockerfile is only a guarantee if these exist.

    Without hashes the flag fails the build; with them, a compromised mirror
    cannot substitute an artifact. Either way this must not silently degrade
    into an unpinned install.
    """
    text = REQUIREMENTS.read_text()

    assert "--hash=sha256:" in text
    pinned = [ln for ln in text.splitlines() if "==" in ln and not ln.startswith("#")]
    assert len(pinned) > 20, "suspiciously few pinned packages"


async def test_the_project_itself_is_not_in_the_export():
    """The entire point: no project version, so a release cannot bust the layer.

    `--no-emit-project` is what keeps this file byte-identical across a version
    bump. If the project ever appears here, the Docker dependency layer starts
    invalidating on every release again and the 490s comes straight back —
    silently, because the build still succeeds.
    """
    for line in REQUIREMENTS.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue  # `# via headroom` is an annotation, not a requirement
        assert not stripped.startswith("headroom=="), (
            "the project is pinned in requirements.txt — regenerate with "
            "--no-emit-project"
        )


async def test_the_dockerfile_installs_from_the_export():
    """Pins the wiring, so the file cannot be left behind as decoration."""
    dockerfile = (ROOT / "Dockerfile").read_text()
    copies = _copy_targets(dockerfile)

    assert "--require-hashes -r requirements.txt" in dockerfile

    req = next(i for i, c in enumerate(copies) if c.startswith("COPY requirements.txt"))
    # The runtime stage copies pyproject.toml too, harmlessly — only the one in
    # the dependency stage matters, so take the FIRST that isn't --chown'd into
    # the runtime image.
    proj = next(
        i for i, c in enumerate(copies)
        if c.startswith("COPY pyproject.toml")
    )
    assert req < proj, (
        "pyproject.toml is copied before the dependency install — that puts the "
        "project version back in front of the layer and reinstates 490s of "
        "rebuild time"
    )
