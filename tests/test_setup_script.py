"""setup.sh's Docker check tells a running daemon from an installed CLI.

It warned only when `docker info || docker --version` BOTH failed — and
`--version` answers from the CLI alone. With the engine installed but not
running (or the user not yet in the docker group) nothing was said, and
`--docker-only` printed "Docker engine ready". These run the real script
against stubbed tools; nothing here installs, starts or sudoes anything.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts" / "setup.sh"
pytestmark = pytest.mark.anyio


def _stub(bindir: Path, name: str, body: str) -> None:
    path = bindir / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


@pytest.fixture
def cli_without_daemon(tmp_path):
    """A `docker` whose CLI answers and whose daemon does not."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub(bindir, "docker", 'if [ "$1" = info ]; then echo "Cannot connect" >&2; exit 1; fi\necho "Docker version 29.0.0"')
    _stub(bindir, "systemctl", "exit 0")
    return bindir


async def test_an_unreachable_daemon_is_warned_about_even_with_the_cli_installed(cli_without_daemon):
    script = (
        f'source "{SETUP}"\n'
        'OS=Linux; SUDO=""\n'
        "ensure_docker\n"
        'echo "READY=$DOCKER_READY"\n'
    )
    env = {**os.environ, "PATH": f"{cli_without_daemon}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, check=True)
    out = result.stdout + result.stderr

    assert "daemon isn't reachable" in out, out
    assert "READY=0" in out


async def test_a_reachable_daemon_is_ready(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub(bindir, "docker", "exit 0")
    script = f'source "{SETUP}"\nensure_docker\necho "READY=$DOCKER_READY"\n'
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, check=True)

    assert "READY=1" in result.stdout
    assert "WARN" not in result.stdout + result.stderr


async def test_docker_only_does_not_announce_an_engine_that_is_not_there(cli_without_daemon):
    """The whole `--docker-only` path, end to end. `uname` reports an OS the
    script does not install on, so it touches nothing and the daemon stays
    down — and it must say so and fail, not print "ready" and exit 0."""
    _stub(cli_without_daemon, "uname", "echo Plan9")
    env = {**os.environ, "PATH": f"{cli_without_daemon}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(
        ["bash", str(SETUP), "--docker-only"], capture_output=True, text=True, env=env, check=False,
    )
    out = result.stdout + result.stderr

    assert result.returncode != 0, out
    assert "Docker engine ready" not in out
    assert "isn't reachable" in out
