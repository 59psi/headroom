"""The suite's own fixtures keep the promises the tests lean on.

A fixture's teardown runs after the test that used it, so no ordinary test can
see whether it happened. These run a small inner session against the real
`tests/conftest.py` in a subprocess and look from the outside.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.anyio

_ROOT = Path(__file__).resolve().parents[1]

_INNER_CONFTEST = """\
# The suite's own fixtures, unchanged: re-exported so this session registers them.
from tests.conftest import *  # noqa: F403 - the point is to take all of them
"""

_INNER_TESTS = """\
import pytest

pytestmark = pytest.mark.anyio
opened = {}


async def test_use_every_client(client, anon_client, file_client):
    opened.update(client=client, anon_client=anon_client, file_client=file_client)
    assert not [name for name, c in opened.items() if c.is_closed]


async def test_each_was_closed_at_teardown():
    assert set(opened) == {"client", "anon_client", "file_client"}
    still_open = sorted(name for name, c in opened.items() if not c.is_closed)
    assert still_open == [], f"left open after their test: {still_open}"
"""

# `test_lifespan_wiring` overrides `client` for its file-backed boot database —
# the same fixture written a second time, and it had the same leak. Imported
# into its own inner module, where it shadows the conftest `client` exactly as
# it does in its home module.
_INNER_BOOT_TESTS = """\
import pytest

from tests.test_lifespan_wiring import app, boot_db, client  # noqa: F401 - fixtures under test

pytestmark = pytest.mark.anyio
opened = {}


async def test_use_the_boot_client(client):
    opened["boot client"] = client
    assert not client.is_closed


async def test_it_was_closed_at_teardown():
    assert set(opened) == {"boot client"}
    assert opened["boot client"].is_closed, "left open after its test: ['boot client']"
"""


async def test_the_client_fixtures_close_what_they_open(tmp_path):
    """`client`, `anon_client` and `file_client` used to `return` an
    `AsyncClient` and never close it — every test in the suite left one
    behind. They are yield fixtures around `async with` now; the second inner
    test fails if any of the three is still open once the first has torn
    down. The lifespan tests' own `client` is held to the same."""
    (tmp_path / "conftest.py").write_text(_INNER_CONFTEST)
    (tmp_path / "test_inner.py").write_text(_INNER_TESTS)
    (tmp_path / "test_inner_boot.py").write_text(_INNER_BOOT_TESTS)

    result = subprocess.run(  # fixed argv, no shell
        [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "-p", "no:randomly", "--rootdir", str(tmp_path), str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(_ROOT), "NO_COLOR": "1"},
    )

    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
    assert "4 passed" in result.stdout, result.stdout[-2000:]
