"""On-demand and scheduled backups of the /data volume.

A backup is a single gzipped tar of the SQLite DB plus the uploads tree.
Streamed on-demand via the admin endpoint, written to disk by the
scheduled job. Retention is enforced after every successful write.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import shutil
import re
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
from headroom.services import ca_vault
from headroom.utils import disk

logger = logging.getLogger(__name__)


class UploadConfigError(Exception):
    """A destination IS configured and no longer resolves to a runnable argv.

    Distinct from `resolve_upload_argv` returning None, which means nothing is
    configured at all. Collapsing the two is how a stored destination that had
    stopped validating produced a silent skip every cycle while the off-site
    card went on showing the previous success.
    """

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

    The SCHEDULER fields are process-local by design, like every other counter
    in this single-process app. A restart resets them, which is correct: the
    question they answer is "is the scheduler working now".

    The UPLOAD fields are not, and must not be — see the note on them below.
    They answer a question about the world rather than about this process, and
    resetting them on restart made the card assert a falsehood.
    """

    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    last_skip_reason: str | None = None
    consecutive_failures: int = 0

    # The off-box copy is tracked SEPARATELY from the backup itself, because
    # the two fail independently and only one of them means "the archive
    # exists nowhere but this SD card". A local backup can succeed every night
    # while the upload has been failing for a month.
    #
    # Unlike everything above, the upload record is PERSISTED (see
    # `_upload_state_path`). It has to be: the question it answers is not "is
    # the scheduler working now" but "does a copy of my data exist off this
    # card, and how old is it" — which is a fact about the world, not about
    # this process. Held only in memory it reset on every restart, and since
    # the scheduler checks once a day, skips the startup backup when a recent
    # one exists, and is change-gated, the card spent nearly all of its time
    # saying nothing had ever been uploaded while uploads were in fact
    # succeeding nightly. A backup report that cannot be trusted when it says
    # "never" is worse than no report at all.
    last_upload_at: datetime | None = None
    last_upload_ok: bool | None = None
    last_upload_error: str | None = None
    #: Filename of the archive the last attempt shipped. "It ran" is not an
    #: answer anyone can act on; the file and the timestamp are.
    last_upload_name: str | None = None
    upload_successes: int = 0
    upload_failures: int = 0

    def record_upload(self, ok: bool, error: str | None = None, name: str | None = None) -> None:
        # Hydrate FIRST. This is the write path, and it does not go through
        # `health()` — the scheduled loop and `_run_upload_hook` both touch the
        # module global directly. Without this the first upload after a restart
        # increments an EMPTY record and overwrites the file with successes=1,
        # wiping the history it exists to keep. That is the very failure this
        # record was added to fix, reintroduced one layer down: the reader was
        # hydrated and the writer was not, so every test that read before
        # writing passed while the unattended nightly path silently reset.
        _ensure_upload_state_loaded(self)
        self.last_upload_at = datetime.now(timezone.utc)
        self.last_upload_ok = ok
        self.last_upload_error = (error or None) if not ok else None
        self.last_upload_name = name or self.last_upload_name
        if ok:
            self.upload_successes += 1
        else:
            self.upload_failures += 1
        _write_upload_state_sync(self)

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

#: Whether the persisted upload record has been restored into `_health` yet.
#: Loaded once per process, lazily, through `health()`.
_upload_state_loaded = False


def health() -> BackupHealth:
    """Current scheduler health. Read-only view for the admin API.

    Restores the persisted upload record on first use. Done here rather than
    at startup because this is the one seam every reader already goes through,
    so there is no path that can observe an empty upload record and report
    "never uploaded" for a box that uploaded last night.
    """
    _ensure_upload_state_loaded()
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


def _add_ca_to_tar(tar: tarfile.TarFile) -> None:
    """Add Caddy's local CA, if this deployment has one and wants it kept.

    The root of this CA is installed by hand on every device that browses the
    site, and a root is self-signed — nothing can vouch for a replacement. So
    losing it is not "reissue a certificate", it is "visit every device". It
    was outside every backup until now, on the same SD card whose unclean
    shutdown started the 37-day outage.

    Never fatal. A backup that skips the CA is worth far more than one that
    fails, so this swallows everything: no overlay, an unreadable mount, a
    half-written export mid-copy.
    """
    if not ca_vault.include_in_backup():
        return
    try:
        files = ca_vault.exported_files()
        if not files:
            return
        for path in files:
            tar.add(path, arcname=f"data/caddy-pki/{path.name}")
        # Travels with the archive, because the archive travels: it may be
        # uploaded to a NAS or cloud by the post-backup hook, and by then
        # nothing else says a private key is inside it.
        note = ca_vault.BACKUP_README.encode()
        info = tarfile.TarInfo(name="data/caddy-pki/READ-ME-CA-KEYS.txt")
        info.size = len(note)
        tar.addfile(info, io.BytesIO(note))
    except Exception:  # a partial backup beats a failed one
        logger.warning("Could not add Caddy CA to backup", exc_info=True)


def _build_tarball_sync(target_path: Path, include_uploads: bool = True) -> None:
    """Build a tar.gz of the DB (and optionally uploads) at `target_path`. Always gzipped.

    `include_uploads=False` produces a DB-only snapshot — useful when the
    photo tree gets large and you only want the metadata captured. Photos
    are JPEG/PNG (already compressed), so gzipping them gains little; if
    you keep originals elsewhere you might never want them in the backup.

    A path is REQUIRED. This used to accept `None` and return the archive as
    `bytes` through a `BytesIO` — a branch no caller used, and the one
    `stream_backup` documents as the way to OOM a 1 GB container holding a
    multi-hundred-megabyte upload tree. A tempting default is how it would
    have come back.
    """
    db = _db_path()
    uploads = settings.upload_dir

    with open(target_path, "wb") as sink:
        # gzip level 6 — same as the default; balances compression and CPU
        # on a Pi. JPEGs barely compress regardless, the DB compresses well.
        with tarfile.open(fileobj=sink, mode="w:gz", compresslevel=6) as tar:
            with tempfile.TemporaryDirectory(prefix="headroom-snap-") as tmp:
                if db is not None and db.exists():
                    _add_db_to_tar(tar, db, Path(tmp))
                if include_uploads and uploads.exists():
                    tar.add(uploads, arcname="data/uploads")
                _add_ca_to_tar(tar)


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

    # The CA counts as data. Without this a regenerated authority would not by
    # itself trigger a backup, so the archive holding the OLD root could age
    # out of the retention window while the new one was never captured.
    if ca_vault.include_in_backup():
        parts.extend(ca_vault.fingerprint_parts())

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


def _upload_state_path() -> Path:
    """Where the last off-box upload is recorded, so a restart can't erase it.

    A file beside the backups, for the same reason `_fingerprint_path` is one
    and emphatically NOT a row in `app_settings`: the database is part of what
    `_data_fingerprint_sync` measures, so writing upload status there would
    change the fingerprint on every upload, every cycle would then see a
    change, and the change-gate would degrade into an unconditional daily
    backup. The fingerprint covers the DB, its WAL and the uploads tree — not
    this directory — so a sidecar here is inert with respect to it.
    """
    return _backup_dir() / ".last-upload"


def _write_upload_state_sync(h: BackupHealth) -> None:
    """Persist the upload record. Never raises — reporting must not break a backup.

    Called straight from `record_upload` rather than through
    `asyncio.to_thread` like `_write_fingerprint_sync`. That asymmetry is
    deliberate: the fingerprint walks the whole uploads tree before writing,
    while this is a two-hundred-byte buffered write and a rename, once per
    upload — at most once a day. Making it async would turn `record_upload`
    into a coroutine and ripple through four call sites to move microseconds
    off the event loop.
    """
    payload = {
        "at": h.last_upload_at.isoformat() if h.last_upload_at else None,
        "ok": h.last_upload_ok,
        "name": h.last_upload_name,
        "error": h.last_upload_error,
        "successes": h.upload_successes,
        "failures": h.upload_failures,
    }
    try:
        path = _upload_state_path()
        # Write-then-rename: a torn file here would read as "never uploaded",
        # which is the exact false negative this whole record exists to remove.
        tmp = path.with_name(path.name + ".tmp")
        # fsync the FILE, then rename, then fsync the DIRECTORY — in that
        # order, which is what the code below does and is not what this comment
        # used to say ("file, then directory, then rename"). The order is the
        # whole mechanism, so describing it backwards is worse than not
        # describing it: syncing the directory before the rename syncs a
        # directory that does not yet contain the rename, and anyone
        # "correcting" the code to match would have silently removed the
        # durability guarantee while the comment went on claiming it.
        #
        # Write-then-rename is atomic against a crash of this process but not
        # against a power cut: without the syncs the rename can reach the disk
        # while the bytes it points at have not, leaving a zero-length file that
        # reads as "never uploaded" — the exact false negative this record
        # exists to remove, produced by the mechanism chosen to prevent it.
        #
        # This is the same argument `HEADROOM_SQLITE_SYNCHRONOUS=FULL` makes,
        # and it was made here after an unclean shutdown on this deployment's SD
        # card destroyed Caddy's private key. One fsync at most once a day is
        # not a cost worth reasoning about.
        with open(tmp, "w") as fh:
            fh.write(json.dumps(payload))
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as exc:
        logger.warning("Could not record backup upload state: %s", exc)


def _read_upload_state_sync() -> dict | None:
    try:
        raw = _upload_state_path().read_text()
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        # A corrupt marker is not evidence of anything. Say nothing rather
        # than assert a "never uploaded" that would be a guess.
        logger.warning("Backup upload state file is unreadable; ignoring it")
        return None
    return data if isinstance(data, dict) else None


def _ensure_upload_state_loaded(target: BackupHealth | None = None) -> None:
    """Restore the persisted upload record, once per process.

    `target` is explicit so the WRITE path can hydrate the object it is about
    to mutate. Hydrating the module singleton while `record_upload` incremented
    `self` would be correct only for as long as those are the same object, and
    the bug this guards against was exactly that kind of near-miss.
    """
    global _upload_state_loaded
    if _upload_state_loaded:
        return
    _upload_state_loaded = True  # set first: a failed read must not retry every call
    health_record = target if target is not None else _health
    data = _read_upload_state_sync()
    if not data:
        return
    raw_at = data.get("at")
    if raw_at:
        try:
            health_record.last_upload_at = datetime.fromisoformat(raw_at)
        except (TypeError, ValueError):
            health_record.last_upload_at = None
    health_record.last_upload_ok = data.get("ok")
    health_record.last_upload_name = data.get("name")
    health_record.last_upload_error = data.get("error")
    for attr, key in (("upload_successes", "successes"), ("upload_failures", "failures")):
        value = data.get(key)
        if isinstance(value, int) and value >= 0:
            setattr(health_record, attr, value)


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


#: The session factory the scheduler's upload hook resolves its argv with. Set
#: by `scheduled_backup_loop(session_factory=)` — the lifespan passes
#: `app.state`'s — and resolved at call time so a module-level default is only
#: ever read when nothing was injected. Imported lazily: `database` imports
#: nothing from here, but the reverse edge was a cycle once and the local
#: import is what the previous code did.
_session_factory = None


def _sessions():
    if _session_factory is not None:
        return _session_factory()
    from headroom.database import async_session  # noqa: PLC0415 — cycle
    return async_session()


async def run_upload(path: Path, argv: list[str] | None = None) -> None:
    """Public entry point for the "Test now" button: run the off-box upload for
    `path` once, recording the outcome exactly as the scheduler would."""
    await _run_upload_hook(path, argv=argv)


async def _run_upload_hook(path: Path, argv: list[str] | None = None) -> None:
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
    # `argv` pre-resolved by the caller when it already holds a session — the
    # test endpoint does, and resolving twice would read the setting twice and
    # leave the two reads free to disagree.
    if argv is None:
        try:
            async with _sessions() as db:
                argv = await resolve_upload_argv(db, path)
        except Exception as exc:  # noqa: BLE001 — never break the backup
            # RECORDED, not just logged. Nobody is reading the container log at
            # 3am; the off-site card is the surface that answers "does a copy of
            # my data exist off this box". Returning silently here left that
            # card showing the last success indefinitely — the exact false
            # confidence the persisted upload record was built to remove.
            logger.error("Could not resolve the backup upload command: %s", exc)
            _health.record_upload(False, f"Upload not attempted: {exc}"[:500], path.name)
            return
    if not argv:
        # No destination configured at all. Correctly silent — an operator who
        # has never set one up is not experiencing a failure, and recording one
        # would put a permanent red state on a feature they declined.
        return
    timeout = backup_upload_timeout()
    try:
        # stdout is discarded, so never buffer it: a verbose uploader
        # (`rclone --progress`) would otherwise stream megabytes into memory
        # for the whole transfer — on a 1 GB Pi that matters.
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=upload_env(),
        )
        try:
            _out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.error(
                "Backup upload timed out after %.0fs: %s", timeout, argv[0]
            )
            _health.record_upload(False, f"Timed out after {timeout:.0f}s", path.name)
            return
        if proc.returncode == 0:
            logger.info("Backup uploaded off-box: %s", path.name)
            _health.record_upload(True, name=path.name)
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
            _health.record_upload(False, f"exit {proc.returncode}: {tail}"[:500], path.name)
    except Exception as exc:  # noqa: BLE001 — off-site copy is best-effort
        logger.error("Backup upload hook error for %s: %s", path.name, exc)
        _health.record_upload(False, str(exc)[:500], path.name)


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


async def scheduled_backup_loop(
    interval_hours: float, keep: int, session_factory=None,
) -> None:
    """Long-running task: writes a backup every `interval_hours`, if anything changed.

    Every failure mode short of cancellation is survivable. This used to run the
    startup age-check and first backup ABOVE the try, and to catch only
    `CancelledError` inside it — so one unwritable `/data` at boot, or a single
    transient `database is locked`, killed the task for the entire life of the
    process. Nothing supervised it and nothing reported it, so the failure
    presented as backups quietly never happening again while the UI kept listing
    the last successful one. For the feature that IS the disaster-recovery
    story, silent permanent death is the worst available behavior.

    Canceled cleanly when the lifespan exits.
    """
    global _session_factory
    _session_factory = session_factory
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
        logger.info("Backup scheduler canceled cleanly.")
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

    `HEADROOM_BACKUP_RETENTION_DAYS` is still honored as a fallback so an
    existing `.env` keeps meaning something rather than silently reverting to
    the default, but it is read as a COUNT now and the name is deprecated.
    Reusing a name whose unit changed would be worse than either.
    """
    keep = env_int("HEADROOM_BACKUP_KEEP", 0)
    if keep > 0:
        return keep
    return env_int("HEADROOM_BACKUP_RETENTION_DAYS", 5)


#: `-a` preserves times and symlinks; owner and group are deliberately NOT
#: preserved. This container runs as uid 1000 and a NAS maps its own users, so
#: asking for them either fails outright or fills the log with warnings about
#: an identity the destination was never going to honor.
_RSYNC_ARGV = ("rsync", "-a", "--no-owner", "--no-group", "{path}", "{dest}")


@dataclass(frozen=True)
class UploadProvider:
    """One way to get a backup off this box.

    A single frozen record drives the argv, the validation, the UI copy and the
    preflight check, so adding a transport is one entry here rather than four
    edits that can disagree — the same shape `settings_service.KeyProvider`
    uses for the external API keys.
    """

    name: str
    label: str
    #: argv TEMPLATE this module owns. The browser never supplies a command; it
    #: supplies a destination, which lands in exactly one slot — so no
    #: arrangement of user input can add a flag, change the binary, or reach a
    #: shell.
    argv: tuple[str, ...]
    #: Anchored, and per-provider because the shapes are genuinely different:
    #: a single colon is a path on a host, a double colon is an rsync DAEMON
    #: module. Accepting both under one pattern would let a typo silently
    #: switch transport.
    destination_re: re.Pattern[str]
    destination_hint: str
    example: str
    #: Checked with `shutil.which` at status time. The whole class of bug this
    #: guards is a feature whose runtime prerequisite is not in the image —
    #: which is exactly how the CA-certificate endpoint shipped broken.
    binary: str
    #: Env var carrying the secret, where the transport accepts one
    #: non-interactively. Read from the host environment and never stored in
    #: the database: a NAS password is not something this app should hold, and
    #: certainly not something it should be able to hand back over the wire.
    secret_env: str | None
    #: What the operator still has to do. Shown in the Settings card, because
    #: "configured" and "working" are different states and the gap between
    #: them is always host-side setup.
    setup: tuple[str, ...]


UPLOAD_PROVIDERS: dict[str, UploadProvider] = {
    "rclone": UploadProvider(
        name="rclone",
        label="Cloud storage (rclone)",
        argv=("rclone", "copy", "{path}", "{dest}"),
        # This does NOT exclude a leading `-`, and the comment here used to say
        # it did. `[A-Za-z0-9_-]` contains `-`, so `-vv:path` and `--config:/x`
        # both match — a "destination" that turns a copy into an
        # arbitrary-config rclone run, flag injection wearing an argument's
        # clothes. What actually stops it is the explicit `startswith("-")`
        # check in `validate_destination`, which every write path goes through.
        # So the hole was never open; the comment was, by naming the wrong
        # guard. That matters more than it sounds: it is the sentence that
        # tells the next person the regex may not be loosened, and it pointed
        # at a property the regex does not have — leaving the real check
        # looking redundant and deletable.
        destination_re=re.compile(r"^[A-Za-z0-9_-]+:[A-Za-z0-9_./ -]*$"),
        destination_hint="remote:path",
        example="box:Headroom-Backups",
        binary="rclone",
        secret_env=None,
        setup=(
            "On the Pi, run `rclone config` and create a remote "
            "(Box, S3, Backblaze B2, Google Drive, Dropbox…).",
            "Headless? Run `rclone authorize \"box\"` on a laptop and paste the "
            "token back.",
            "`chmod 644 ~/.config/rclone/rclone.conf` so the container user can "
            "read it.",
            "Bring the stack up with the rclone overlay: "
            "`-f docker-compose.backup-rclone.yml`.",
            "Put the remote name and path in the field above, then press Test now.",
        ),
    ),
    "rsync": UploadProvider(
        name="rsync",
        label="rsync over SSH",
        argv=_RSYNC_ARGV,
        # One colon, and the path may not contain another — so a destination
        # meant for SSH cannot quietly become a daemon-mode `::` target.
        destination_re=re.compile(r"^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:[A-Za-z0-9_./ -]*$"),
        destination_hint="user@host:/path",
        example="pi@nas.local:/volume1/backups/headroom",
        binary="rsync",
        secret_env=None,
        setup=(
            "Create an SSH key for the backup on the Pi: "
            "`ssh-keygen -t ed25519 -f ~/.ssh/headroom-backup -N \"\"`.",
            "Authorize it on the destination: "
            "`ssh-copy-id -i ~/.ssh/headroom-backup.pub user@host`.",
            "Connect once by hand so the host key is recorded — an unknown host "
            "key makes the upload hang, not fail.",
            "Bring the stack up with the rsync overlay: "
            "`-f docker-compose.backup-rsync.yml` (it mounts the key and "
            "known_hosts read-only).",
            "Put the destination above, then press Test now.",
        ),
    ),
    "synology": UploadProvider(
        name="synology",
        label="Synology NAS (rsync service)",
        argv=_RSYNC_ARGV,
        # DOUBLE colon: rsync connects straight to the daemon on port 873 and
        # the first path segment is a MODULE name, not a directory.
        destination_re=re.compile(r"^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+::[A-Za-z0-9_./ -]+$"),
        destination_hint="user@host::module/path",
        example="backup@synology.local::backups/headroom",
        binary="rsync",

        # password. The value is read from the host at upload time and is
        # deliberately never stored, logged, or returned by the API.
        secret_env="HEADROOM_BACKUP_RSYNC_PASSWORD",  # noqa: S106
        setup=(
            "**Find your module name first — do not assume it.** Run "
            "`rsync rsync://HOST/` (GNU rsync, e.g. from inside this "
            "container) to list what the daemon offers. DSM exposes your "
            "SHARED FOLDERS as modules, so a real NAS lists things like "
            "`home`, `homes`, `photo`, `video`, `docker` — the name varies per "
            "install. Guessing gives `@ERROR: Unknown module '…'`.",
            "**You do not need `NetBackup`.** Any shared folder the daemon "
            "lists works as a module, so point at one you already have. "
            "Control Panel → File Services → rsync → **Enable network backup "
            "service** simply adds one MORE module, named `NetBackup`, "
            "alongside your shared folders — it is an option, not a "
            "requirement, and the list from step 1 is what to trust.",
            "Control Panel → File Services → rsync → rsync Account: add an "
            "account and password. This is a separate rsync account, not your "
            "DSM login.",
            "If the NAS firewall is on, allow port 873.",
            "On the Pi, put that account's password in `.env` as "
            "`HEADROOM_BACKUP_RSYNC_PASSWORD=…` and restart the stack. It is "
            "read from the host environment and never stored by Headroom.",
            "Note for macOS: `rsync` there is **openrsync** (protocol 29), "
            "which does not parse `user@host::module` and reports the whole "
            "thing as an unresolvable hostname. Use GNU rsync — the one in "
            "this container is 3.4.1.",
            "Destination above uses TWO colons — `user@host::module/path`. "
            "That is what makes rsync talk to the DAEMON on port 873 instead "
            "of tunneling over SSH, and it makes the first segment a MODULE "
            "name rather than a directory. It has nothing to do with the "
            "network backup service checkbox.",
        ),
    ),
}

UPLOAD_PROVIDER_KEY = "backup_upload_provider"
UPLOAD_DESTINATION_KEY = "backup_upload_destination"


async def list_rsync_modules(destination: str, timeout: float = 10.0) -> list[str]:
    """Module names the rsync daemon behind `destination` actually offers.

    Exists because "Unknown module 'NetBackup'" is a dead end on its own. DSM
    derives modules from your SHARED FOLDERS, so the real list is
    install-specific and cannot be documented — only discovered. Telling an
    operator to go and run `rsync HOST::` themselves is a poor substitute for
    this container, which already has GNU rsync, simply asking.

    Anonymous: module listing happens before authentication, so no credential
    is needed and none is passed. Returns [] on any failure — this only ever
    enriches an error message and must never raise on that path.
    """
    host = destination.split("@")[-1].split("::", 1)[0]
    if not host:
        return []
    try:
        proc = await asyncio.create_subprocess_exec(
            "rsync", f"--contimeout={int(timeout)}", f"rsync://{host}/",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
    except Exception as exc:  # noqa: BLE001 — decoration only
        logger.info("Could not list rsync modules on %s: %s", host, exc)
        return []
    # `name<TAB>comment` per line; the name is all we need.
    return [
        line.split("\t", 1)[0].strip()
        for line in out.decode("utf-8", "replace").splitlines()
        if line.strip()
    ]


def binary_available(binary: str) -> bool:
    """Is this executable on PATH inside the container?

    The single answer to that question. The test endpoint used to re-derive it
    with its own `shutil.which(argv[0])`, which meant two places could disagree
    about whether an upload could possibly run.
    """
    return shutil.which(binary) is not None


def provider_binary_available(provider: str) -> bool | None:
    """Is the transport's binary actually in this container?

    None when the provider is unknown. Worth surfacing rather than discovering
    at 3am: none of these binaries are in the base image, and a missing one
    fails every unattended upload while the card still reads "configured".
    """
    p = UPLOAD_PROVIDERS.get(provider or "")
    if p is None:
        return None
    return binary_available(p.binary)


def validate_destination(dest: str, provider: str = "rclone") -> str:
    """Return a cleaned destination for `provider`, or raise ValueError.

    Deliberately strict rather than clever. This value becomes an argument to
    a subprocess that runs unattended on every backup, so the safe move is to
    accept only the shape the transport documents and reject everything else.
    """
    spec = UPLOAD_PROVIDERS.get(provider or "")
    if spec is None:
        raise ValueError(f"Unknown provider. Available: {sorted(UPLOAD_PROVIDERS)}")
    cleaned = (dest or "").strip()
    if not cleaned:
        raise ValueError(f"Destination is required, e.g. {spec.example}")
    if cleaned.startswith("-"):
        raise ValueError("Destination may not start with '-' (that is a flag, not a remote).")
    if not spec.destination_re.match(cleaned):
        raise ValueError(
            f"Destination must look like {spec.destination_hint} "
            f"(e.g. {spec.example}) — letters, digits, '_', '-', '.', '/' "
            "and spaces only."
        )
    return cleaned


async def resolve_upload_argv(db, path: Path) -> list[str] | None:
    """The argv to run for `path`, or None when no upload is configured.

    Environment WINS over the stored setting, which is the opposite of the
    precedence used for API keys — and deliberately so. `HEADROOM_BACKUP_UPLOAD_CMD`
    is a raw command, settable only by someone with host access, and that is a
    privilege boundary. Letting a browser override a host-level decision about
    what executes on every backup would erase it.
    """
    raw = backup_upload_cmd()
    if raw:
        return [
            tok.replace("{path}", str(path))
            .replace("{dir}", str(path.parent))
            .replace("{name}", path.name)
            for tok in shlex.split(raw)
        ]

    from headroom.services import settings_service  # noqa: PLC0415 — cycle

    provider = await settings_service.get_setting(db, UPLOAD_PROVIDER_KEY)
    dest = await settings_service.get_setting(db, UPLOAD_DESTINATION_KEY)
    spec = UPLOAD_PROVIDERS.get(provider or "")
    if spec is None or not dest:
        return None
    try:
        # Re-validated against THIS provider's pattern, not the one it was
        # saved under: switching provider without re-entering the destination
        # would otherwise carry an SSH path into daemon mode, or the reverse.
        dest = validate_destination(dest, spec.name)
    except ValueError as exc:
        # A stored value that no longer validates is a configuration error, not
        # a reason to run something unexpected.
        #
        # RAISED rather than returned as None, because None already means
        # "nothing is configured" and the two must not look alike to the
        # caller. They did: an operator who had set up an off-site copy and
        # then changed provider without re-entering the destination got a
        # silent skip on every cycle, while `BackupHealth` kept showing the
        # last SUCCESS — a green card asserting a copy that had stopped being
        # made. Silence is the right answer to "no destination"; it is the
        # wrong answer to "the destination you configured no longer works".
        logger.error("Stored backup destination is invalid, upload skipped: %s", exc)
        raise UploadConfigError(str(exc)) from exc
    return [tok.replace("{path}", str(path)).replace("{dest}", dest) for tok in spec.argv]


def upload_env() -> dict[str, str] | None:
    """Extra environment for the upload subprocess, or None to inherit as-is.

    `RSYNC_PASSWORD` is rsync's documented way to authenticate to a DAEMON
    (`host::module`) without a terminal. It does **not** apply to rsync over
    SSH — rsync ignores it there — which is why the SSH provider carries no
    secret at all rather than one that would look set and do nothing.

    Keyed on the environment rather than the provider because the value is
    inert to every other binary here, and threading the provider name through
    the hook to gate an ignored variable would buy nothing.
    """
    password = os.environ.get("HEADROOM_BACKUP_RSYNC_PASSWORD", "").strip()
    if not password:
        return None
    return {**os.environ, "RSYNC_PASSWORD": password}


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
