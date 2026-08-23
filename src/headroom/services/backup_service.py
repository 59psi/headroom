"""On-demand and scheduled backups of the /data volume.

A backup is a single gzipped tar of the SQLite DB plus the uploads tree.
Streamed on-demand via the admin endpoint, written to disk by the
scheduled job. Retention is enforced after every successful write.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import shutil
import shlex
import stat
import tarfile
import tempfile
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from headroom.config import env_flag, env_float, env_int, settings
from headroom.utils import disk

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
    last_skip_reason: str | None = None
    consecutive_failures: int = 0

    def record_success(self) -> None:
        now = datetime.now(timezone.utc)
        self.last_attempt_at = now
        self.last_success_at = now
        self.last_error = None
        self.last_skip_reason = None
        self.consecutive_failures = 0

    def record_skipped(self, reason: str) -> None:
        """A cycle that ran and correctly decided not to write anything.

        Distinct from both success and failure. Without it a change-gated
        scheduler looks stalled: `last_attempt_at` would stop advancing on an
        idle collection and read exactly like a dead task, which is the
        confusion this whole record exists to prevent. Consecutive failures
        are deliberately left alone — skipping is not a recovery.
        """
        self.last_attempt_at = datetime.now(timezone.utc)
        self.last_skip_reason = reason

    def record_failure(self, reason: Exception | str) -> None:
        """Accepts a string as well as an exception.

        The most likely failure does NOT arrive as an exception here:
        `write_scheduled_backup` catches its own and returns None, so the loop
        sees a falsy return and nothing else. Taking only an Exception is how
        that path came to be recorded as a SUCCESS.
        """
        self.last_attempt_at = datetime.now(timezone.utc)
        self.last_error = (
            f"{type(reason).__name__}: {reason}" if isinstance(reason, Exception)
            else str(reason)
        )[:500]
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


def _enforce_retention(keep: int) -> None:
    """Keep the newest `keep` backups and delete the rest.

    COUNT-based, and the history of this function is worth carrying. It was
    count-based once before, and combined with a backup written at every
    process start it let a crash/restart loop mint N same-hour snapshots and
    evict the real history. The fix at the time was to switch to age.

    Age is now the wrong policy, because backups are only written when the
    data has actually changed. Age-pruning and change-gating combine into a
    trap: leave the collection alone for longer than the retention window and
    the last backup ages out with nothing to replace it — a policy whose
    steady state, on an idle system, is **zero backups**. Counting cannot do
    that. It also means N backups now span as much history as the collection
    took to change N times, rather than a fixed N days.

    The original hazard is handled at the other end: the startup backup is
    conditional, and an unchanged cycle writes nothing at all.
    """
    if keep <= 0:
        return
    backups = _list_backups_sync()  # newest first
    for p in backups[keep:]:
        try:
            p.unlink()
        except OSError as exc:
            logger.warning("Failed to prune old backup %s: %s", p, exc)


def _fingerprint_path() -> Path:
    """Where the last backed-up state's signature lives.

    A file beside the backups, deliberately NOT a row in `app_settings`: the
    database is part of what the fingerprint measures, so storing it there
    would change the thing being measured every time it was written, and
    every cycle would then look like a change. A self-defeating cache.
    """
    return _backup_dir() / ".last-fingerprint"


def _data_fingerprint_sync() -> str:
    """A cheap signature of everything a backup would capture.

    Size and mtime rather than content: hashing a gigabyte of photos to decide
    whether to copy a gigabyte of photos is worse than the problem. The failure
    mode of a metadata fingerprint is an edit that changes neither size nor
    mtime, which on this data means someone rewriting a file in place with
    identical bytes — and that is not an edit.

    Both the database file AND its `-wal` sidecar are measured. In WAL mode a
    commit lands in the sidecar and may not touch the main file at all, so
    watching `headroom.db` alone would call a day of edits "no changes".
    """
    parts: list[str] = []

    db = _db_path()
    if db is not None:
        for path in (db, db.with_name(f"{db.name}-wal")):
            try:
                st = path.stat()
                parts.append(f"{path.name}:{st.st_size}:{st.st_mtime_ns}")
            except OSError:
                parts.append(f"{path.name}:-")

    count = total = 0
    newest = 0.0
    uploads = settings.upload_dir
    if uploads.exists():
        for p in uploads.rglob("*"):
            try:
                st = p.stat()
            except OSError:
                continue  # vanished mid-walk; the next cycle will see it
            if not stat.S_ISREG(st.st_mode):
                continue
            count += 1
            total += st.st_size
            newest = max(newest, st.st_mtime)
    parts.append(f"uploads:{count}:{total}:{newest:.0f}")

    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def _read_fingerprint_sync() -> str | None:
    try:
        return _fingerprint_path().read_text().strip() or None
    except OSError:
        return None


def _write_fingerprint_sync(value: str) -> None:
    try:
        _fingerprint_path().write_text(value)
    except OSError as exc:
        # Losing the marker costs one redundant backup next cycle, which is a
        # far better failure than skipping a real one — so this never raises.
        logger.warning("Could not record backup fingerprint: %s", exc)


def _seconds_since_newest_backup_sync() -> float | None:
    """Age of the newest backup in seconds, or None if there are none."""
    backups = _list_backups_sync()
    if not backups:
        return None
    return time.time() - backups[0].stat().st_mtime


async def newest_backup_at() -> datetime | None:
    """When the newest backup on disk was written, or None if there are none.

    The fallback behind `BackupHealth.last_success_at`. The in-memory record
    is process-local by design, and on this deployment a restart is the normal
    state of affairs — a restart policy, Pi power cycles, and `docker compose
    up -d --build` as the documented way to upgrade. So the endpoint named
    *health* was the one that forgot, and `last_success_at: null` after a
    reboot is indistinguishable from "this has never once worked".

    A file's mtime is weaker evidence than a recorded outcome: it says a
    backup was written, not that the scheduler is alive to write another. That
    is why the reading is flagged as derived rather than silently substituted
    — a caller that can tell them apart can say which one it is looking at.
    """
    backups = await list_backups()
    if not backups:
        return None
    try:
        return datetime.fromtimestamp(backups[0].stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


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
            # ERROR: best-effort means it does not fail the local backup, not
            # that nobody needs to know. A silently-failing upload hook is how
            # the off-site copy everyone believes in turns out not to exist.
            logger.error(
                "Backup upload failed (rc=%s) for %s: %s",
                proc.returncode, path.name, tail,
            )
    except Exception as exc:  # noqa: BLE001 — off-site copy is best-effort
        logger.error("Backup upload hook error for %s: %s", path.name, exc)


async def write_scheduled_backup(keep: int, fingerprint: str | None = None) -> Path | None:
    """Write a timestamped tarball to /data/backups, enforce retention, and
    (if configured) ship it off-box.

    Returns the new file path, or None on failure. A failed off-box upload does
    NOT fail the local backup — the file is on disk and the path is returned.
    """
    try:
        target = _backup_dir() / _timestamped_name()
        await asyncio.to_thread(_build_tarball_sync, target)
        await asyncio.to_thread(_enforce_retention, keep)
        if fingerprint is not None:
            # AFTER the tarball is on disk, never before: a marker written for
            # a backup that then failed would suppress every later attempt
            # until something changed again.
            await asyncio.to_thread(_write_fingerprint_sync, fingerprint)
        logger.info("Scheduled backup written: %s", target.name)
    except Exception as exc:  # noqa: BLE001 — never crash the scheduler
        # ERROR, matching the loop's own handler for the same condition. This
        # was WARNING while the identical failure one frame up was logged via
        # `logger.exception` — so the disaster-recovery feature failing was
        # findable or not depending on which of two paths it took, and on the
        # likely path it sat at the same severity as "mDNS: no LAN address".
        logger.error("Scheduled backup failed: %s", exc)
        return None
    await _run_upload_hook(target)  # best-effort, never raises
    return target


async def scheduled_backup_loop(interval_hours: float, keep: int) -> None:
    """Long-running task: writes a backup every `interval_hours`, if anything changed.

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
        "Backup scheduler started: check every %.1f hours, keep newest %d, "
        "write only when the data has changed, dir=%s",
        interval_hours, keep, settings.upload_dir.parent / BACKUP_DIR_NAME,
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
                    # Nothing changed since the last successful backup? Then
                    # the next tarball would restate one already on disk, at
                    # the cost of re-reading every photo, several hundred MB of
                    # SD-card wear, and one slot of real history evicted from a
                    # fixed-size window. The marker lives OUTSIDE the database
                    # precisely so that writing it does not itself count as a
                    # change — a cache stored in the thing it measures would
                    # invalidate itself every time it was updated.
                    #
                    # Computed only when due: the fingerprint walks the whole
                    # uploads tree, which is not free on a Pi and is pure waste
                    # on a cycle that was never going to write anything.
                    fingerprint = await asyncio.to_thread(_data_fingerprint_sync)
                    previous = await asyncio.to_thread(_read_fingerprint_sync)

                    if fingerprint == previous:
                        # Recorded, not silent. An idle collection would
                        # otherwise stop advancing `last_attempt_at`, which
                        # looks exactly like a scheduler that has died.
                        _health.record_skipped("No changes since the last backup.")
                        logger.info(
                            "Scheduled backup skipped — nothing has changed "
                            "since the last one."
                        )
                    else:
                        # Say something about the disk before writing several
                        # hundred megabytes to it. This loop is the only thing
                        # that runs on a timer and touches the volume in bulk,
                        # so it is where the card filling up gets noticed — and
                        # a full disk is the likeliest cause of the failure
                        # logged below, which turns a stack trace into a
                        # diagnosis.
                        space = await asyncio.to_thread(
                            disk.check, settings.upload_dir
                        )
                        if not space.ok:
                            logger.error(
                                "Low disk space before scheduled backup: %s — "
                                "below the %d MB floor; the backup will "
                                "probably fail.",
                                space.summary(), disk.min_free_mb(),
                            )
                        elif space.low:
                            logger.warning(
                                "Disk space getting low: %s (warning below %.0f%%).",
                                space.summary(), disk.warn_pct(),
                            )

                        # CHECK THE RETURN. `write_scheduled_backup` swallows
                        # its own exception and returns None, so calling
                        # record_success() unconditionally reported a backup
                        # that failed every cycle as healthy — the exact
                        # blindness this health record exists to remove.
                        written = await write_scheduled_backup(keep, fingerprint)
                        if written is None:
                            _health.record_failure(
                                "Backup failed — see the preceding log line "
                                "for the cause."
                            )
                        else:
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


def backup_keep() -> int:
    """How many backups to keep. Count, not days — see `_enforce_retention`.

    `HEADROOM_BACKUP_RETENTION_DAYS` is still honoured as a fallback so an
    existing `.env` keeps meaning something rather than silently reverting to
    the default, but it is read as a COUNT now and the name is deprecated.
    Reusing a name whose unit changed would be worse than either.
    """
    keep = env_int("HEADROOM_BACKUP_KEEP", 0)
    if keep > 0:
        return keep
    return env_int("HEADROOM_BACKUP_RETENTION_DAYS", 5)


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
