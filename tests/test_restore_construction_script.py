"""scripts/restore-construction.py works the way its docstring says to run it.

Its documented usage was `python3 scripts/restore-construction.py
/data/backups/...` "on the box running Headroom", against a hardcoded
`/data/headroom.db`. On Docker the script is not in the image and `/data` is a
named volume, not a host path; on bare metal the database is `./headroom.db`.
The usage is now "feed it to the container's Python on stdin", with the live
database resolved the way the app resolves its own — so that is what runs here.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "restore-construction.py"
pytestmark = pytest.mark.anyio


def _db(path: Path, rows: dict[int, str | None]) -> Path:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE hats (id INTEGER PRIMARY KEY, construction TEXT, "
        "hydro INTEGER DEFAULT 0, hydrolite INTEGER DEFAULT 0)"
    )
    conn.executemany("INSERT INTO hats (id, construction) VALUES (?, ?)", rows.items())
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def backup_and_live(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    old = _db(tmp_path / "headroom.db.old", {1: "HYDRO", 2: "HYDROLite"})
    archive = backups / "headroom-backup-2026-09-01T00-00-00Z.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(old, arcname="data/headroom.db")
    live = _db(tmp_path / "live.db", {1: "Classic", 2: "HYDROLite"})
    return archive, live


def _run_as_documented(archive: Path, *extra: str, database_url: str) -> subprocess.CompletedProcess:
    """`python - <archive> < scripts/restore-construction.py` — the Docker
    recipe, minus the `docker compose exec -T headroom` in front of it."""
    env = {**os.environ, "HEADROOM_DATABASE_URL": database_url}
    return subprocess.run(  # fixed argv, no shell
        [sys.executable, "-", str(archive), *extra],
        stdin=SCRIPT.open("rb"), capture_output=True, env=env, cwd=ROOT, check=False,
    )


async def test_the_documented_stdin_invocation_finds_the_apps_database(backup_and_live):
    archive, live = backup_and_live

    result = _run_as_documented(archive, database_url=f"sqlite+aiosqlite:///{live}")
    out = result.stdout.decode() + result.stderr.decode()

    assert result.returncode == 0, out
    assert "1 hat(s) differ" in out
    assert "Dry run" in out


async def test_apply_writes_to_the_apps_database_and_nothing_else(backup_and_live):
    archive, live = backup_and_live

    result = _run_as_documented(archive, "--apply", database_url=f"sqlite+aiosqlite:///{live}")

    assert result.returncode == 0, result.stderr.decode()
    rows = dict(sqlite3.connect(live).execute("SELECT id, construction FROM hats"))
    assert rows == {1: "HYDRO", 2: "HYDROLite"}
    # Extraction happened beside the archive and was cleaned up.
    assert sorted(p.name for p in archive.parent.iterdir()) == [archive.name]


async def test_a_restored_value_is_recorded_as_the_owners(backup_and_live):
    """The construction audit's bulk clear skips an OWNER's value by
    `construction_source`. A restore writes back what the owner typed, so it
    has to say so — left alone, the column kept describing the value it
    replaced, and the restored construction was the next sweep's to clear."""
    archive, live = backup_and_live
    conn = sqlite3.connect(live)
    conn.execute("ALTER TABLE hats ADD COLUMN construction_source VARCHAR(20)")
    conn.execute("UPDATE hats SET construction_source = 'owner' WHERE id = 2")
    conn.commit()
    conn.close()

    result = _run_as_documented(archive, "--apply", database_url=f"sqlite+aiosqlite:///{live}")

    assert result.returncode == 0, result.stderr.decode()
    rows = {
        r[0]: r[1:] for r in sqlite3.connect(live).execute(
            "SELECT id, construction, construction_source, hydro, hydrolite FROM hats"
        )
    }
    assert rows[1] == ("HYDRO", "owner", 1, 0), "the restored value is not recorded as the owner's"
    assert rows[2] == ("HYDROLite", "owner", 0, 0), "a hat the restore did not touch changed"


async def test_the_scripts_owner_source_is_the_apps():
    """Restated in the script (it runs without the app installed too); held
    to the one definition here."""
    import importlib.util

    from headroom.services import construction_audit

    spec = importlib.util.spec_from_file_location("restore_construction", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._OWNER_SOURCE == construction_audit.OWNER_SOURCE
