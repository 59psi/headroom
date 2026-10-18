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


@pytest.fixture
def stubbed_setup(tmp_path):
    """The real setup.sh in a scratch tree, every tool it runs a stub that
    records its arguments. It `cd`s to its own parent, so nothing it does can
    reach this checkout."""
    tree = tmp_path / "tree"
    (tree / "scripts").mkdir(parents=True)
    (tree / "frontend").mkdir()
    (tree / "scripts" / "setup.sh").write_bytes(SETUP.read_bytes())
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "calls.log"
    record = f'echo "$(basename "$0") $*" >> "{calls}"'
    # `$FAIL_UV_RUN` makes `uv run …` (the import) fail, as a "no" at its
    # prompt or a refusal does.
    _stub(bindir, "uv", f'{record}\n[ "$1" = run ] && [ -n "${{FAIL_UV_RUN:-}}" ] && exit 1\nexit 0')
    _stub(bindir, "node", "echo v26.12.0")
    _stub(bindir, "npm", f'if [ "$1" = --version ]; then echo 12.2.0; exit 0; fi\n{record}')
    _stub(bindir, "npx", record)
    _stub(bindir, "git", "exit 128")  # "not a git checkout": no build stamp
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}

    def run(*args: str, **extra_env: str) -> tuple[subprocess.CompletedProcess, str]:
        result = subprocess.run(
            ["bash", str(tree / "scripts" / "setup.sh"), "--no-docker", *args],
            capture_output=True, text=True, env={**env, **extra_env}, check=False,
        )
        return result, calls.read_text() if calls.exists() else ""

    return tree, run


async def test_setup_leaves_the_database_to_the_app(stubbed_setup):
    """setup.sh ran `init_db` itself, so re-running it to upgrade bare metal
    migrated the database before the app could save the pre-upgrade copy it
    promises: the boot that followed snapshotted an already-migrated file."""
    tree, run = stubbed_setup
    result, calls = run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "init_db" not in calls and "python -c" not in calls, calls
    assert not (tree / "uploads").exists(), "setup made ./uploads, which HEADROOM_UPLOAD_DIR may not be"


async def test_setup_builds_the_spa_the_way_the_image_does(stubbed_setup):
    """`npm run build` is `tsc -b && vite build`; a bare `vite build` skipped
    the type check the Dockerfile and CI both run."""
    _, run = stubbed_setup
    result, calls = run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "npm run build" in calls, calls
    assert "vite build" not in calls.replace("npm run build", ""), calls


async def test_setup_imports_a_backup_through_the_apps_own_import(stubbed_setup, tmp_path):
    backup = tmp_path / "old-headroom.db"
    backup.write_bytes(b"SQLite format 3\x00")
    _, run = stubbed_setup
    result, calls = run("--import", str(backup))

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"uv run python -m headroom.import_database {backup}" in calls, calls


async def test_a_declined_import_does_not_abort_the_setup(stubbed_setup, tmp_path):
    """Answering "no" (or a refusal) exits the import non-zero; under
    `set -e` that ended setup before the build stamp, the git hooks and the
    closing instructions."""
    backup = tmp_path / "old-headroom.db"
    backup.write_bytes(b"SQLite format 3\x00")
    _, run = stubbed_setup
    result, _calls = run("--import", str(backup), FAIL_UV_RUN="1")
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert "did not happen" in out
    assert "Setup complete" in out


async def test_no_dev_leaves_out_the_python_dev_tools(stubbed_setup):
    _, run = stubbed_setup
    result, calls = run("--no-dev")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "uv sync --no-dev" in calls

    _, plain = run()
    assert "uv sync\n" in plain, "a development setup lost its test tools"


async def test_setup_refuses_an_import_it_cannot_read(stubbed_setup, tmp_path):
    _, run = stubbed_setup
    result, calls = run("--import", str(tmp_path / "missing.db"))

    assert result.returncode != 0
    assert "Cannot read" in result.stdout + result.stderr
    assert calls == "", "setup started installing before refusing its arguments"
