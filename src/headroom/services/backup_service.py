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
import shutil
import shlex
import tarfile
import tempfile
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from headroom.config import env_flag, env_float, env_int, settings

logger = logging.getLogger(__name__)

BACKUP_DIR_NAME = "backups"
BACKUP_PREFIX = "headroom-backup-"
BACKUP_SUFFIX = ".tar.gz"


@dataclass
class BackupHealth:
    """Whether the scheduler is actually working, not merely still running.

    The list of files on disk cannot answer that: a scheduler that died three
    weeks ago and one that ran ten minutes ago look identical from the
    inventory, and the newest file is the last SUCCESS either way. So the
    outcome of each attempt is recorded here and surfaced through the admin
    API, which is what makes a persistent failure visible before the day it
    matters.

    Process-local by design, like every other counter in this single-process
    app. A restart resets it, which is correct: the question it answers is
    "is the scheduler working now".
    """

    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0

    def record_success(self) -> None:
        now = datetime.now(timezone.utc)
        self.last_attempt_at = now
        self.last_success_at = now
        self.last_error = None
        self.consecutive_failures = 0

    def record_failure(self, exc: Exception) -> None:
        self.last_attempt_at = datetime.now(timezone.utc)
        self.last_error = f"{type(exc).__name__}: {exc}"[:500]
        self.consecutive_failures += 1


_health = BackupHealth()


def health() -> BackupHealth:
    """Current scheduler health. Read-only view for the admin API."""
    return _health


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


def _snapshot_db_sync(db: Path, dest_dir: Path) -> Path:
    """Produce a single-file, point-in-time copy of the SQLite DB.

    The DB runs in WAL mode (`database.py`), so commits live in
    `headroom.db-wal` until a checkpoint folds them back into the main file.
    Adding only `headroom.db` to the tar therefore silently drops everything
    committed since the last checkpoint — and since a checkpoint can land
    *during* the tar's read, the copy can also come out torn and restore as
    "database disk image is malformed". Either way the failure is invisible
    until the day you actually need the backup.

    `VACUUM INTO` asks SQLite for the snapshot instead of copying bytes behind
    its back: it holds a read transaction, folds in the WAL, and writes one
    self-contained file with no sidecars. Writers are not blocked.

    Falls back to the raw file set (main + `-wal` + `-shm`) if the snapshot
    fails for any reason — a restorable-with-effort backup beats no backup.
    """
    import sqlite3  # noqa: PLC0415 — stdlib, only needed on the backup path

    dest = dest_dir / db.name
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        conn.execute("VACUUM INTO ?", (str(dest),))
    finally:
        conn.close()
    return dest


def _add_db_to_tar(tar: tarfile.TarFile, db: Path, tmp_dir: Path) -> None:
    """Add a consistent DB snapshot, or the raw file set if that fails."""
    try:
        snapshot = _snapshot_db_sync(db, tmp_dir)
        tar.add(snapshot, arcname=f"data/{db.name}")
        return
    except Exception as exc:  # noqa: BLE001 — never let backup fail entirely
        # Bound to an outer name on purpose: Python unbinds the `except` target
        # when the block exits, and the reason is needed below.
        reason = exc
        logger.warning(
            "DB snapshot failed (%s); falling back to raw file + WAL sidecars", exc
        )
    tar.add(db, arcname=f"data/{db.name}")
    for sidecar in (f"{db.name}-wal", f"{db.name}-shm"):
        path = db.with_name(sidecar)
        if path.exists():
            tar.add(path, arcname=f"data/{sidecar}")
    # Mark the archive itself. The fallback copies the DB file while writers may
    # be mid-transaction, so it can restore as "database disk image is
    # malformed" — and until now the resulting tarball was byte-indistinguishable
    # from a clean snapshot, so the one moment you find out is the restore. A
    # file inside the archive travels with it; a log line does not.
    note = (
        f"This backup was taken with the RAW-FILE fallback, not VACUUM INTO,\n"
        f"because the snapshot failed:\n\n    {reason}\n\n"
        f"The database file was copied while it may have been mid-write, so it\n"
        f"may be torn. Restore it, then run `PRAGMA integrity_check;` before\n"
        f"trusting it. A clean backup has no file like this one.\n"
    ).encode()
    info = tarfile.TarInfo(name="data/DEGRADED-BACKUP-README.txt")
    info.size = len(note)
    tar.addfile(info, io.BytesIO(note))


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
            with tempfile.TemporaryDirectory(prefix="headroom-snap-") as tmp:
                if db is not None and db.exists():
                    _add_db_to_tar(tar, db, Path(tmp))
                if include_uploads and uploads.exists():
                    tar.add(uploads, arcname="data/uploads")
        if buf is not None:
            return buf.getvalue()
        return None
    finally:
        if target_path is not None:
            sink.close()


_STREAM_CHUNK = 1024 * 1024


async def stream_backup(include_uploads: bool = True) -> AsyncGenerator[bytes, None]:
    """Build the tarball to a temp FILE, then stream it back in chunks.

    It previously built into an in-memory `BytesIO` and yielded the whole thing
    as one chunk, on the reasoning that "a few hundred MB at most" is fine on a
    Pi. It isn't: that is the entire database plus the whole uploads tree
    resident at once, on the same box that holds a ~179MB rembg model, and it
    is now over the container's memory limit — so the one operation whose
    purpose is protecting the data could kill the process.

    Spooling to disk trades RAM for temp space, which a Pi has far more of, and
    caps memory at one chunk. `StreamingResponse` was already the caller; only
    now is it streaming anything.
    """
    tmp_dir = tempfile.mkdtemp(prefix="headroom-stream-")
    tmp_path = Path(tmp_dir) / "backup.tar.gz"
    try:
        await asyncio.to_thread(_build_tarball_sync, tmp_path, include_uploads)
        with tmp_path.open("rb") as fh:
            while True:
                # Off the loop: a 1MB read from an SD card is not instant, and
                # blocking here stalls every other request.
                chunk = await asyncio.to_thread(fh.read, _STREAM_CHUNK)
                if not chunk:
                    break
                yield chunk
    finally:
        # Runs even if the client disconnects mid-download, which closes the
        # generator — without this, an abandoned download leaks a full copy of
        # the collection into temp space until reboot.
        shutil.rmtree(tmp_dir, ignore_errors=True)


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
    timeout = backup_upload_timeout()
    try:
        argv = [
            tok.replace("{path}", str(path))
            .replace("{dir}", str(path.parent))
            .replace("{name}", path.name)
            for tok in shlex.split(cmd)
        ]
        # stdout is discarded, so never buffer it: a verbose uploader
        # (`rclone --progress`) would otherwise stream megabytes into memory
        # for the whole transfer — on a 1 GB Pi that matters.
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning(
                "Backup upload timed out after %.0fs: %s", timeout, argv[0]
            )
            return
        if proc.returncode == 0:
            logger.info("Backup uploaded off-box: %s", path.name)
        else:
            # Slice the bytes before decoding — only the tail is logged, and a
            # chatty failure shouldn't cost a full-size str to throw away.
            tail = (err or b"")[-4000:].decode("utf-8", "replace").strip()[-500:]
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

    Every failure mode short of cancellation is survivable. This used to run the
    startup age-check and first backup ABOVE the try, and to catch only
    `CancelledError` inside it — so one unwritable `/data` at boot, or a single
    transient `database is locked`, killed the task for the entire life of the
    process. Nothing supervised it and nothing reported it, so the failure
    presented as backups quietly never happening again while the UI kept listing
    the last successful one. For the feature that IS the disaster-recovery
    story, silent permanent death is the worst available behaviour.

    Cancelled cleanly when the lifespan exits.
    """
    interval_s = max(60.0, interval_hours * 3600.0)
    logger.info(
        "Backup scheduler started: every %.1f hours, keep %d days, dir=%s",
        interval_hours, retention, settings.upload_dir.parent / BACKUP_DIR_NAME,
    )
    first_pass = True
    try:
        while True:
            try:
                if first_pass:
                    # Startup backup only if the newest existing snapshot is
                    # older than one interval. A fresh deploy (no backups) gets
                    # one; a crash/restart loop does NOT spam same-hour backups
                    # — the previous unconditional startup backup was half of
                    # the history-destruction bug (count-based pruning was the
                    # other).
                    age = await asyncio.to_thread(_seconds_since_newest_backup_sync)
                    due = age is None or age >= interval_s
                else:
                    due = True
                if due:
                    await write_scheduled_backup(retention)
                    _health.record_success()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Keep looping. A full disk, a read-only mount or a locked DB
                # are all transient in principle, and retrying in an hour costs
                # nothing next to never backing up again.
                _health.record_failure(exc)
                logger.exception(
                    "Scheduled backup failed (%d consecutive); retrying in %.1f h",
                    _health.consecutive_failures, interval_s / 3600.0,
                )
            first_pass = False
            await asyncio.sleep(interval_s)
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
    return env_float("HEADROOM_BACKUP_INTERVAL_HOURS", 24.0)


def backup_retention() -> int:
    return env_int("HEADROOM_BACKUP_RETENTION_DAYS", 7)


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
    return env_float("HEADROOM_BACKUP_UPLOAD_TIMEOUT", 600.0)
