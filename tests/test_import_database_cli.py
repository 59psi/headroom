"""The two terminal doors into a database import, run for real.

`python -m headroom.import_database` in a subprocess against scratch
databases, and `scripts/import-database.sh` against a stub `docker` that
records what it is asked to do and how many bytes it was fed — the script's
whole job is the order of those calls, and that the app comes back up.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from headroom.services import instance_lock
from tests import conftest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.anyio


async def _backup_with_a_hat(client, path: Path, model: str) -> Path:
    resp = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "odysea", "model_name": model}
    )
    assert resp.status_code in (200, 201), resp.text
    async with conftest.test_engine.connect() as conn:
        await conn.exec_driver_sql("VACUUM INTO ?", (str(path),))
    return path


def _cli(live: Path, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "HEADROOM_DATABASE_URL": f"sqlite+aiosqlite:///{live}",
        "HEADROOM_UPLOAD_DIR": str(live.parent / "uploads"),
    }
    return subprocess.run(  # fixed argv, no shell
        [sys.executable, "-m", "headroom.import_database", *args],
        input=stdin, capture_output=True, env=env, cwd=ROOT, check=False,
    )


async def test_the_command_line_sets_up_a_fresh_install_from_a_backup(client, tmp_path):
    backup = await _backup_with_a_hat(client, tmp_path / "backup.db", "Carried Across")
    live = tmp_path / "new-machine" / "headroom.db"
    live.parent.mkdir()

    preview = _cli(live, "--preview", str(backup))
    assert preview.returncode == 0, preview.stderr.decode()
    assert not live.exists(), "a preview created the database it was only comparing against"

    result = _cli(live, "--yes", str(backup))
    assert result.returncode == 0, result.stderr.decode()
    conn = sqlite3.connect(live)
    try:
        assert [r[0] for r in conn.execute("SELECT model_name FROM hats")] == ["Carried Across"]
        # A fresh install has no account to keep, so the backup's comes with it.
        assert [r[0] for r in conn.execute("SELECT username FROM users")] == ["testowner"]
    finally:
        conn.close()


async def test_the_command_line_will_not_import_unconfirmed_from_stdin(client, tmp_path):
    backup = await _backup_with_a_hat(client, tmp_path / "backup.db", "Unconfirmed")
    live = tmp_path / "live" / "headroom.db"
    live.parent.mkdir()

    result = _cli(live, "-", stdin=backup.read_bytes())

    assert result.returncode == 2
    assert b"--yes" in result.stderr
    conn = sqlite3.connect(live)
    try:
        assert conn.execute("SELECT COUNT(*) FROM hats").fetchone()[0] == 0
    finally:
        conn.close()


async def test_the_command_line_refuses_while_the_app_holds_the_data_directory(client, tmp_path):
    """The app holds `<data dir>/.headroom.lock` while it runs. An import
    beside it would swap hats out from under its workers, so the command line
    refuses — before it has touched the live database at all."""
    backup = await _backup_with_a_hat(client, tmp_path / "backup.db", "Never Imported")
    live = tmp_path / "running" / "headroom.db"
    live.parent.mkdir()
    holder = os.open(live.parent / instance_lock.LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(holder, fcntl.LOCK_EX)
    try:
        result = _cli(live, "--yes", str(backup))
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)

    assert result.returncode == 1
    assert b"Headroom is running" in result.stderr
    assert not live.exists(), "the refused import still created or migrated the live database"


async def test_an_app_started_during_an_import_waits_for_it():
    """`acquire_waiting` is the boot's side: it returns once the holder lets
    go, rather than failing (a watchdog restart mid-import) or running beside
    it."""
    held = instance_lock.try_acquire()
    assert held is not None
    assert instance_lock.try_acquire() is None
    threading.Timer(0.3, instance_lock.release, args=(held,)).start()

    fd = await asyncio.to_thread(instance_lock.acquire_waiting, 0.05)

    assert fd is not None
    instance_lock.release(fd)


async def test_a_refusal_is_one_sentence_not_a_traceback(tmp_path):
    junk = tmp_path / "notes.txt"
    junk.write_text("hello")
    live = tmp_path / "live" / "headroom.db"
    live.parent.mkdir()

    result = _cli(live, "--yes", str(junk))

    assert result.returncode == 1
    err = result.stderr.decode()
    assert err.startswith("Not imported:"), err
    assert "Traceback" not in err


# ---- scripts/import-database.sh ----------------------------------------------- #


@pytest.fixture
def docker_tree(tmp_path):
    """The real script (and the upgrade.sh it sources) in a scratch tree, with
    a `docker` that logs each call — and, for `compose run`, the bytes it read
    from stdin — and fails the import when `$FAIL_IMPORT` is set."""
    tree = tmp_path / "tree"
    (tree / "scripts").mkdir(parents=True)
    for name in ("import-database.sh", "upgrade.sh"):
        (tree / "scripts" / name).write_bytes((ROOT / "scripts" / name).read_bytes())
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "docker.log"
    docker = bindir / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        f'LOG="{log}"\n'
        'case "$1 $2" in\n'
        '  "compose ls") echo "[]"; exit 0 ;;\n'
        '  "compose run") n=$(wc -c | tr -d " "); echo "$* <$n bytes>" >> "$LOG";\n'
        '     case "$*" in *--yes*) [ -n "${FAIL_IMPORT:-}" ] && exit 1 ;; esac; exit 0 ;;\n'
        "esac\n"
        'if [ "$1" = inspect ]; then echo healthy; exit 0; fi\n'
        'echo "$*" >> "$LOG"\n'
    )
    docker.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}

    def run(*args: str, **extra_env: str) -> tuple[subprocess.CompletedProcess, list[str]]:
        result = subprocess.run(
            ["bash", str(tree / "scripts" / "import-database.sh"), *args],
            capture_output=True, text=True, env={**env, **extra_env}, check=False,
            stdin=subprocess.DEVNULL,
        )
        return result, log.read_text().splitlines() if log.exists() else []

    return run


async def test_the_script_previews_then_stops_imports_and_starts_the_app(docker_tree, tmp_path):
    backup = tmp_path / "backup.tar.gz"
    backup.write_bytes(b"x" * 1234)

    result, calls = docker_tree(str(backup), "--yes")

    assert result.returncode == 0, result.stdout + result.stderr
    run = "compose run --rm --no-deps -T headroom python -m headroom.import_database"
    assert calls == [
        f"{run} --preview - <1234 bytes>",
        "compose stop headroom",
        f"{run} --yes - <1234 bytes>",
        "compose start headroom",
    ], calls


async def test_a_failed_import_still_starts_the_app(docker_tree, tmp_path):
    backup = tmp_path / "backup.db"
    backup.write_bytes(b"x")

    result, calls = docker_tree(str(backup), "--yes", FAIL_IMPORT="1")

    assert result.returncode != 0
    assert "was not replaced" in result.stdout + result.stderr
    assert calls[-1] == "compose start headroom", "a refused import left the app stopped"


async def test_the_script_asks_first_and_changes_nothing_on_no(docker_tree, tmp_path):
    backup = tmp_path / "backup.db"
    backup.write_bytes(b"x")

    result, calls = docker_tree(str(backup))  # stdin is empty: the answer is "no"

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Nothing changed" in result.stdout
    assert all("stop" not in c and "--yes" not in c for c in calls), calls
