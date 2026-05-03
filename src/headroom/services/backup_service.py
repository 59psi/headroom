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
import tarfile
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

from headroom.config import settings

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


def _build_tarball_sync(target_path: Path | None = None) -> bytes | None:
    """Build a tar.gz of DB + uploads. If target_path given, also write to disk.

    Returns the bytes when target_path is None (for streaming), else None.
    """
    db = _db_path()
    uploads = settings.upload_dir

    buf: io.BytesIO | None = None
    sink = open(target_path, "wb") if target_path else (buf := io.BytesIO())

    try:
        with tarfile.open(fileobj=sink, mode="w:gz") as tar:
            if db is not None and db.exists():
                tar.add(db, arcname=f"data/{db.name}")
            if uploads.exists():
                # arcname keeps relative structure under data/uploads/
                tar.add(uploads, arcname="data/uploads")
        if buf is not None:
            return buf.getvalue()
        return None
    finally:
        if target_path is not None:
            sink.close()


async def stream_backup() -> AsyncGenerator[bytes, None]:
    """Build the tarball off the event loop, then yield it as one chunk.

    Streaming-the-tar-as-it's-built would be more elegant but tarfile's
    blocking IO model makes that significantly more complex; for the data
    sizes we expect on a Pi (a few hundred MB at most) one buffered chunk
    is fine.
    """
    payload = await asyncio.to_thread(_build_tarball_sync, None)
    if payload:
        yield payload


def _timestamped_name() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"{BACKUP_PREFIX}{ts}{BACKUP_SUFFIX}"


def _list_backups_sync() -> list[Path]:
    return sorted(
        (p for p in _backup_dir().iterdir()
         if p.is_file() and p.name.startswith(BACKUP_PREFIX) and p.name.endswith(BACKUP_SUFFIX)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


async def list_backups() -> list[Path]:
    return await asyncio.to_thread(_list_backups_sync)


def _enforce_retention(retention: int) -> None:
    if retention <= 0:
        return
    keep = _list_backups_sync()[:retention]
    keep_set = {p.name for p in keep}
    for p in _list_backups_sync():
        if p.name not in keep_set:
            try:
                p.unlink()
            except OSError as exc:
                logger.warning("Failed to prune old backup %s: %s", p, exc)


async def write_scheduled_backup(retention: int) -> Path | None:
    """Write a timestamped tarball to /data/backups, enforce retention.

    Returns the new file path, or None on failure.
    """
    try:
        target = _backup_dir() / _timestamped_name()
        await asyncio.to_thread(_build_tarball_sync, target)
        await asyncio.to_thread(_enforce_retention, retention)
        logger.info("Scheduled backup written: %s", target.name)
        return target
    except Exception as exc:  # noqa: BLE001 — never crash the scheduler
        logger.warning("Scheduled backup failed: %s", exc)
        return None


async def scheduled_backup_loop(interval_hours: float, retention: int) -> None:
    """Long-running task: writes a backup every `interval_hours`.

    Cancelled cleanly when the lifespan exits.
    """
    interval_s = max(60.0, interval_hours * 3600.0)
    logger.info(
        "Backup scheduler started: every %.1f hours, keep %d, dir=%s",
        interval_hours, retention, _backup_dir(),
    )
    # Initial backup at startup so a fresh deploy has at least one snapshot.
    await write_scheduled_backup(retention)
    try:
        while True:
            await asyncio.sleep(interval_s)
            await write_scheduled_backup(retention)
    except asyncio.CancelledError:
        logger.info("Backup scheduler cancelled cleanly.")
        raise


def streaming_filename() -> str:
    return _timestamped_name()


# --- Env-var sourced config (kept here, not in pydantic Settings, so a misset
#     value can't crash the whole app — backups become a no-op instead). ---


def backup_enabled() -> bool:
    return os.environ.get("HEADROOM_BACKUP_ENABLED", "true").lower() in ("1", "true", "yes")


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
