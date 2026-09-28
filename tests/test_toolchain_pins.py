"""The Node toolchain is one set of numbers, stated in several files.

The Node MAJOR the image builds on lives in the Dockerfile's `FROM node:`,
CI's `node-version` and setup.sh's NodeSource URLs; the Node versions a
checkout can BUILD on live in every locked package's `engines`, in
`frontend/package.json` and in setup.sh's `node_ok`. Nothing held them
together, and they drifted exactly as the owner's change-ripple note records:
setup.sh accepted 22.22+ while jsdom 30 — locked, with `engine-strict` on —
accepts only `^22.22.2 || ^24.15.0 || >=26.0.0`. Node 24.0, an LTS line,
passed setup and then died in `npm ci` with EBADENGINE.

`test_the_npm_pin_is_one_number_in_three_files` (test_docs_consistency.py)
does this for npm. These do it for Node, by EVALUATING the ranges over a grid
of real version numbers rather than comparing their spelling.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts" / "setup.sh"
pytestmark = pytest.mark.anyio

Version = tuple[int, int, int]


# ---- a small npm-semver evaluator ------------------------------------------ #
#
# Only what `engines` fields use. Anything it does not understand RAISES, so a
# dependency that starts writing ranges a new way fails here loudly instead of
# being evaluated as "anything goes".

_COMPARATOR = re.compile(r"^(>=|<=|>|<|=|\^|~)?v?(\*|x|X|\d+)(?:\.(\*|x|X|\d+))?(?:\.(\*|x|X|\d+))?$")


def _partial(groups) -> list[int | None]:
    return [None if g in (None, "*", "x", "X") else int(g) for g in groups]


def _bump(parts: list[int | None]) -> Version:
    """The first version above everything `parts` names (an x-range's ceiling)."""
    major, minor, _ = parts
    if minor is None:
        return (major + 1, 0, 0)
    return (major, minor + 1, 0)


def _floor(parts: list[int | None]) -> Version:
    return tuple(p or 0 for p in parts)  # type: ignore[return-value]


def _comparator_ok(v: Version, token: str) -> bool:
    match = _COMPARATOR.match(token)
    if not match:
        raise ValueError(f"unsupported engines comparator {token!r}")
    op = match.group(1) or "="
    parts = _partial(match.groups()[1:])
    if parts[0] is None:
        return True  # `*`
    exact = None not in parts
    if op == "=":
        return v == _floor(parts) if exact else _floor(parts) <= v < _bump(parts)
    if op == ">=":
        return v >= _floor(parts)
    if op == ">":
        return v > _floor(parts) if exact else v >= _bump(parts)
    if op == "<":
        return v < _floor(parts)
    if op == "<=":
        return v <= _floor(parts) if exact else v < _bump(parts)
    if op == "^":
        major, minor, _ = parts
        if major > 0 or minor is None:
            ceiling = (major + 1, 0, 0)
        elif minor > 0 or parts[2] is None:
            ceiling = (0, minor + 1, 0)
        else:
            ceiling = _floor(parts)[:2] + (parts[2] + 1,)  # type: ignore[operator]
        return _floor(parts) <= v < ceiling
    if op == "~":
        ceiling = _bump([parts[0], parts[1], None]) if parts[1] is not None else _bump([parts[0], None, None])
        return _floor(parts) <= v < ceiling
    raise AssertionError(op)


def satisfies(v: Version, spec: str) -> bool:
    for alternative in spec.split("||"):
        alternative = alternative.strip()
        hyphen = re.fullmatch(r"(\S+)\s+-\s+(\S+)", alternative)
        if hyphen:
            tokens = [f">={hyphen.group(1)}", f"<={hyphen.group(2)}"]
        else:
            # `>= 12.0.0` — an operator separated from its version.
            tokens = re.sub(r"(>=|<=|>|<|=|\^|~)\s+", r"\1", alternative).split()
        if all(_comparator_ok(v, t) for t in tokens or ["*"]):
            return True
    return False


# ---- the grid ---------------------------------------------------------------- #

GRID: list[Version] = sorted(
    {(major, minor, patch) for major in range(16, 33) for minor in range(0, 32) for patch in (0, 2, 9)}
    | {(22, 22, 1), (22, 22, 2), (24, 14, 9), (24, 15, 0), (26, 0, 0)}
)


def _lock_ranges() -> dict[str, str]:
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text())
    ranges = {}
    for name, meta in lock["packages"].items():
        if not name:
            continue  # the project itself: its own `engines` is what is checked
        engines = meta.get("engines")
        if isinstance(engines, dict) and "node" in engines:
            ranges[name] = engines["node"]
    return ranges


def _npm_ci_accepts() -> set[Version]:
    """Every grid version that every locked package's `engines` accepts."""
    ranges = _lock_ranges()
    assert ranges, "no engines fields found — the lockfile format changed?"
    return {v for v in GRID if all(satisfies(v, r) for r in ranges.values())}


def _setup_accepts(versions: list[Version]) -> set[Version]:
    """Run setup.sh's REAL `node_ok` against a stubbed `node`, once per version."""
    listing = " ".join(".".join(map(str, v)) for v in versions)
    script = (
        f'source "{SETUP}"\n'
        'node() { echo "v$FAKE_NODE"; }\n'
        f"for FAKE_NODE in {listing}; do\n"
        '  if node_ok; then echo "$FAKE_NODE"; fi\n'
        "done\n"
    )
    result = subprocess.run(  # fixed script, no user input
        ["bash", "-c", script], capture_output=True, text=True, check=True,
    )
    return {tuple(int(x) for x in line.split(".")) for line in result.stdout.split()}


def _fmt(versions) -> str:
    return ", ".join(".".join(map(str, v)) for v in sorted(versions)[:8])


# ---- the tests ---------------------------------------------------------------- #


async def test_the_evaluator_reads_the_ranges_that_matter_correctly():
    """Pinned against the range that caused this, so the grid means something."""
    jsdom = "^22.22.2 || ^24.15.0 || >=26.0.0"
    assert satisfies((22, 22, 2), jsdom) and satisfies((24, 15, 0), jsdom)
    assert satisfies((26, 0, 0), jsdom) and satisfies((31, 4, 1), jsdom)
    for refused in [(22, 22, 1), (23, 11, 0), (24, 0, 0), (24, 14, 9), (25, 2, 0)]:
        assert not satisfies(refused, jsdom), refused
    assert satisfies((22, 12, 0), "^20.19.0 || >=22.12.0")
    assert satisfies((12, 0, 0), ">= 12.0.0")
    assert satisfies((20, 1, 0), "20 || >=22") and not satisfies((21, 0, 0), "20 || >=22")
    assert satisfies((16, 20, 0), ">=v12.22.7")


async def test_setup_accepts_exactly_the_node_versions_npm_ci_will_run_on():
    """Wider, and setup passes a Node that `npm ci` then refuses with
    EBADENGINE. Narrower, and it reinstalls a Node that would have worked."""
    wanted = _npm_ci_accepts()
    got = _setup_accepts(GRID)
    assert not got - wanted, f"setup.sh accepts Node that npm ci refuses: {_fmt(got - wanted)}"
    assert not wanted - got, f"setup.sh refuses Node that npm ci accepts: {_fmt(wanted - got)}"


async def test_package_json_states_the_same_node_range():
    engines = json.loads((ROOT / "frontend" / "package.json").read_text())["engines"]["node"]
    wanted = _npm_ci_accepts()
    stated = {v for v in GRID if satisfies(v, engines)}
    assert stated == wanted, (
        f"frontend/package.json says {engines!r}; the lockfile accepts a different set. "
        f"Over: {_fmt(stated - wanted)}; under: {_fmt(wanted - stated)}"
    )


async def test_the_node_major_is_one_number_everywhere_it_is_installed():
    dockerfile = (ROOT / "Dockerfile").read_text()
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    setup = SETUP.read_text()

    image = re.search(r"^FROM node:(\d+)-", dockerfile, re.M).group(1)
    ci_major = re.search(r"^\s*node-version:\s*(\d+)\s*$", ci, re.M).group(1)
    setup_major = re.search(r"^NODE_INSTALL_MAJOR=(\d+)$", setup, re.M).group(1)

    assert ci_major == image, f"CI builds on Node {ci_major}; the image on {image}"
    assert setup_major == image, f"setup.sh installs Node {setup_major}; the image builds on {image}"
    # The install URLs use the variable, not a copy of the number.
    assert re.findall(r"nodesource\.com/setup_([^\"]+)\"", setup) == [
        "${NODE_INSTALL_MAJOR}.x", "${NODE_INSTALL_MAJOR}.x",
    ]
    # And what gets installed is something the lockfile will build on.
    assert (int(image), 0, 0) in _npm_ci_accepts()


async def test_the_dockerfile_frontend_floats_on_its_major():
    """A minor pin here has no updater: Dependabot reads FROM lines only.
    `docker/dockerfile:1` is Docker's channel for the latest stable 1.x."""
    first = (ROOT / "Dockerfile").read_text().splitlines()[0]
    assert first == "# syntax=docker/dockerfile:1", first
