"""A database snapshot before a new version's first boot migrates it.

Every release note that changed the schema used to open with "take a backup
first" — a step a person has to remember, on the one day they are thinking
about something else (the new feature, the overlay flags). And the migrations
that run on the first boot of a new version are exactly the ones that cannot
be undone by reverting the image: 2.81.0 rebuilt the whole `hats` table.

So the app takes the backup itself. Before `init_db` touches the schema, the
lifespan compares the version it is about to run with the one recorded by the
last successful boot (`last_booted_version` in `app_settings`); when they
differ it writes a one-file copy of the database next to the scheduled
archives, as `backups/pre-upgrade-<from>-to-<to>-<UTC time>.db`. The version
is recorded only after migrations and the one-time repairs succeed, so a boot
that dies half-way snapshots again on the next attempt rather than trusting a
record of an upgrade that never finished.

What it deliberately is not: a replacement for the scheduled archives (it has
the database only — photos are not changed by a migration) or a restore
mechanism. Restoring one is the documented recipe: stop the app, copy the file
over `/data/headroom.db`, remove `headroom.db-wal` and `headroom.db-shm`.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

logger = logging.getLogger(__name__)

#: `app_settings` key holding the version of the last boot that got through
#: migrations and repairs.
LAST_BOOTED_KEY = "last_booted_version"
SNAPSHOT_PREFIX = "pre-upgrade-"
#: Snapshots kept. Three upgrades back is the useful window — past that, the
#: nightly archives are the better restore point — and each file is a whole
#: database, so an unbounded count is a slow disk leak on a Pi's SD card.
KEEP = 3


def running_version() -> str:
    """The version this process is about to run."""
    try:
        return version("headroom")
    except PackageNotFoundError:
        return "0+unknown"


def sqlite_file(url) -> Path | None:
    """The database file behind an engine URL; None for memory or non-SQLite.

    Taken from the engine the lifespan was handed, not from `settings`, so a
    test booting against its own file snapshots THAT file.
    """
    if not url.drivername.startswith("sqlite"):
        return None
    database = url.database
    if not database or database == ":memory:" or database.startswith("file:"):
        return None
    return Path(database) if Path(database).is_absolute() else Path.cwd() / database


def _file_part(text: str) -> str:
    """A version string made safe for a file name (`2.81.0`, `0+unknown`)."""
    return re.sub(r"[^A-Za-z0-9.+-]", "_", text)[:40] or "unknown"


def last_booted(db: Path) -> str | None:
    """The recorded version, or None: never recorded, or no settings table yet."""
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (LAST_BOOTED_KEY,)
        ).fetchone()
    except sqlite3.OperationalError:
        # A database from before `app_settings` existed. Old enough that the
        # upgrade ahead of it is large — which is the case to snapshot.
        return None
    finally:
        conn.close()
    return row[0] if row else None


def snapshot_before_upgrade(db: Path | None, dest_dir: Path, current: str) -> Path | None:
    """Copy the database to `dest_dir` if `current` is not the last booted version.

    Returns the snapshot's path, or None when there was nothing to protect:
    not a file database, a fresh install (no file, or an empty one), or the
    same version as last boot.

    A normal connection, not the read-only one the live archive uses. At boot
    nothing else has the database open, and after an unclean stop the
    committed transactions may still be in `-wal` — a read-only connection
    cannot always recover a WAL, and a snapshot that silently left them out
    would be a backup of the database as it was BEFORE its newest changes.
    """
    if db is None or not db.exists() or db.stat().st_size == 0:
        return None
    previous = last_booted(db)
    if previous == current:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    versions = f"{_file_part(previous or 'unknown')}-to-{_file_part(current)}"
    name = f"{SNAPSHOT_PREFIX}{versions}-{stamp}.db"
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / name
    # Written under a temporary name and renamed into place, as the archives
    # are: a snapshot cut short by a full disk must never look like a good one.
    partial = dest_dir / f"{name}.partial"
    partial.unlink(missing_ok=True)
    conn = sqlite3.connect(db)
    try:
        conn.execute("VACUUM INTO ?", (str(partial),))
    finally:
        conn.close()
    partial.replace(final)
    prune(dest_dir)
    return final


def prune(dest_dir: Path, keep: int = KEEP) -> list[Path]:
    """Delete all but the newest `keep` snapshots (and stray `.partial` files)."""
    removed: list[Path] = []
    for stray in dest_dir.glob(f"{SNAPSHOT_PREFIX}*.db.partial"):
        stray.unlink(missing_ok=True)
        removed.append(stray)
    snapshots = sorted(
        dest_dir.glob(f"{SNAPSHOT_PREFIX}*.db"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for old in snapshots[keep:]:
        old.unlink(missing_ok=True)
        removed.append(old)
    return removed
