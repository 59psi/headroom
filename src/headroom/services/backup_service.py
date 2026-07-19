"""On-demand and scheduled backups of the /data volume.

A backup is a single gzipped tar of the SQLite DB plus the uploads tree.
Streamed on-demand via the admin endpoint, written to disk by the
scheduled job. Retention is enforced after every successful write.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import shlex
import tarfile
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

from headroom.config import env_flag, settings

logger = logging.getLogger(__name__)

BACKUP_DIR_NAME = "backups"
BACKUP_PREFIX = "headroom-backup-"
BACKUP_SUFFIX = ".tar.gz"


def _backup_dir() -> Path:
    d = settings.upload_dir.parent / BACKUP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _db_path() -> Path | None:
    """Best-effort resolution of the SQLite file path from the connection URL."""
    url = settings.database_url
    if not url.startswith("sqlite"):
        return None
    # forms: sqlite+aiosqlite:///./headroom.db, sqlite+aiosqlite:////data/headroom.db
    if ":///" not in url:
        return None
    raw = url.split(":///", 1)[1]
    if raw.startswith("/"):
        return Path(raw)
    return Path.cwd() / raw


def _build_tarball_sync(target_path: Path | None = None, include_uploads: bool = True) -> bytes | None:
    """Build a tar.gz of the DB (and optionally uploads). Always gzipped.

    `include_uploads=False` produces a DB-only snapshot — useful when the
    photo tree gets large and you only want the metadata captured. Photos
    are JPEG/PNG (already compressed), so gzipping them gains little; if
    you keep originals elsewhere you might never want them in the backup.
    """
    db = _db_path()
    uploads = settings.upload_dir

    buf: io.BytesIO | None = None
    sink = open(target_path, "wb") if target_path else (buf := io.BytesIO())

    try:
        # gzip level 6 — same as the default; balances compression and CPU
        # on a Pi. JPEGs barely compress regardless, the DB compresses well.
        with tarfile.open(fileobj=sink, mode="w:gz", compresslevel=6) as tar:
            if db is not None and db.exists():
                tar.add(db, arcname=f"data/{db.name}")
            if include_uploads and uploads.exists():
                tar.add(uploads, arcname="data/uploads")
        if buf is not None:
            return buf.getvalue()
        return None
    finally:
        if target_path is not None:
            sink.close()


async def stream_backup(include_uploads: bool = True) -> AsyncGenerator[bytes, None]:
    """Build the tarball off the event loop, then yield it as one chunk.

    Streaming-the-tar-as-it's-built would be more elegant but tarfile's
    blocking IO model makes that significantly more complex; for the data
    sizes we expect on a Pi (a few hundred MB at most) one buffered chunk
    is fine.
    """
    payload = await asyncio.to_thread(_build_tarball_sync, None, include_uploads)
    if payload:
        yield payload


def _timestamped_name(suffix: str = "") -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    extra = f"-{suffix}" if suffix else ""
    return f"{BACKUP_PREFIX}{ts}{extra}{BACKUP_SUFFIX}"


def _list_backups_sync() -> list[Path]:
    return sorted(
        (p for p in _backup_dir().iterdir()
         if p.is_file() and p.name.startswith(BACKUP_PREFIX) and p.name.endswith(BACKUP_SUFFIX)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


async def list_backups() -> list[Path]:
    return await asyncio.to_thread(_list_backups_sync)


def _enforce_retention(retention_days: int) -> None:
    """Delete backups older than `retention_days`, honoring the env-var name.

    This is deliberately AGE-based, not count-based: the previous count-based
    prune, combined with a backup written at every process start, let a
    crash/restart loop mint N same-hour backups and evict the real daily
    history. Age-based pruning only removes genuinely old snapshots, and the
    newest file is never deleted (never leave zero backups on disk).
    """
    if retention_days <= 0:
        return
    backups = _list_backups_sync()  # newest first
    if len(backups) <= 1:
        return
    cutoff = time.time() - retention_days * 86400
    for p in backups[1:]:  # always keep the most recent snapshot
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError as exc:
            logger.warning("Failed to prune old backup %s: %s", p, exc)


def _seconds_since_newest_backup_sync() -> float | None:
    """Age of the newest backup in seconds, or None if there are none."""
    backups = _list_backups_sync()
    if not backups:
        return None
    return time.time() - backups[0].stat().st_mtime


async def _run_upload_hook(path: Path) -> None:
    """Best-effort off-box copy of a freshly written backup.

    Runs ``HEADROOM_BACKUP_UPLOAD_CMD`` (e.g. ``rclone copy {path} box:Backups``)
    with ``{path}`` / ``{dir}`` / ``{name}`` substituted. Parsed as an argv with
    ``shlex`` — no shell — so a placeholder expands to a single argument even if
    a path contains spaces.

    NEVER raises: an upload failure, timeout, or missing uploader binary must
    not break the local backup or the scheduler loop — the tarball is already
    safely on disk. The upload target is the operator's problem to keep tidy;
    Headroom only prunes the local copies.
    """
    cmd = backup_upload_cmd()
    if not cmd:
        return
    try:
        argv = [
            tok.replace("{path}", str(path))
            .replace("{dir}", str(path.parent))
            .replace("{name}", path.name)
            for tok in shlex.split(cmd)
        ]
        if not argv:
            return
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _out, err = await asyncio.wait_for(
                proc.communicate(), timeout=backup_upload_timeout()
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning(
                "Backup upload timed out after %.0fs: %s",
                backup_upload_timeout(), argv[0],
            )
            return
        if proc.returncode == 0:
            logger.info("Backup uploaded off-box: %s", path.name)
        else:
            tail = (err or b"").decode("utf-8", "replace").strip()[-500:]
            logger.warning(
                "Backup upload failed (rc=%s) for %s: %s",
                proc.returncode, path.name, tail,
            )
    except Exception as exc:  # noqa: BLE001 — off-site copy is best-effort
        logger.warning("Backup upload hook error for %s: %s", path.name, exc)


async def write_scheduled_backup(retention: int) -> Path | None:
    """Write a timestamped tarball to /data/backups, enforce retention, and
    (if configured) ship it off-box.

    Returns the new file path, or None on failure. A failed off-box upload does
    NOT fail the local backup — the file is on disk and the path is returned.
    """
    try:
        target = _backup_dir() / _timestamped_name()
        await asyncio.to_thread(_build_tarball_sync, target)
        await asyncio.to_thread(_enforce_retention, retention)
        logger.info("Scheduled backup written: %s", target.name)
    except Exception as exc:  # noqa: BLE001 — never crash the scheduler
        logger.warning("Scheduled backup failed: %s", exc)
        return None
    await _run_upload_hook(target)  # best-effort, never raises
    return target


async def scheduled_backup_loop(interval_hours: float, retention: int) -> None:
    """Long-running task: writes a backup every `interval_hours`.

    Cancelled cleanly when the lifespan exits.
    """
    interval_s = max(60.0, interval_hours * 3600.0)
    logger.info(
        "Backup scheduler started: every %.1f hours, keep %d days, dir=%s",
        interval_hours, retention, _backup_dir(),
    )
    # Startup backup only if the newest existing snapshot is older than one
    # interval. A fresh deploy (no backups) gets one; a crash/restart loop does
    # NOT spam same-hour backups — the previous unconditional startup backup was
    # half of the history-destruction bug (with count-based pruning as the other).
    age = await asyncio.to_thread(_seconds_since_newest_backup_sync)
    if age is None or age >= interval_s:
        await write_scheduled_backup(retention)
    try:
        while True:
            await asyncio.sleep(interval_s)
            await write_scheduled_backup(retention)
    except asyncio.CancelledError:
        logger.info("Backup scheduler cancelled cleanly.")
        raise


def streaming_filename(include_uploads: bool = True) -> str:
    return _timestamped_name(suffix="" if include_uploads else "db-only")


# --- Env-var sourced config (kept here, not in pydantic Settings, so a misset
#     value can't crash the whole app — backups become a no-op instead). ---


def backup_enabled() -> bool:
    return env_flag("HEADROOM_BACKUP_ENABLED")


def backup_interval_hours() -> float:
    try:
        return float(os.environ.get("HEADROOM_BACKUP_INTERVAL_HOURS", "24"))
    except ValueError:
        return 24.0


def backup_retention() -> int:
    try:
        return int(os.environ.get("HEADROOM_BACKUP_RETENTION_DAYS", "7"))
    except ValueError:
        return 7


def backup_upload_cmd() -> str:
    """Command run after each scheduled backup to ship it off-box (empty = off).

    Placeholders: ``{path}`` (full path to the new tarball), ``{dir}`` (its
    directory), ``{name}`` (filename). Sourced from the env here, not pydantic
    Settings, so a misset value degrades the upload to a no-op instead of
    crashing the app.
    """
    return os.environ.get("HEADROOM_BACKUP_UPLOAD_CMD", "").strip()


def backup_upload_timeout() -> float:
    """Seconds to allow the upload command before killing it (default 600)."""
    try:
        return float(os.environ.get("HEADROOM_BACKUP_UPLOAD_TIMEOUT", "600"))
    except ValueError:
        return 600.0
