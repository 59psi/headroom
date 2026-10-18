"""One process at a time owns the data directory: the app, or an import.

The app is single-process by design — its queues, rate limiter and staging
registry are in memory — and nothing enforced that across PROCESSES. That
mattered once a second kind of process could write the same database: the
command-line import (`python -m headroom.import_database`). Run while the app
is up, the swap would land under a worker writing to hat #12 by id; and
`scripts/import-database.sh` stops the app for the import, but a watchdog that
sees the app down restarts it, mid-import, by design.

So the app holds an exclusive `flock` on `<data dir>/.headroom.lock` for as
long as it runs, and an import takes the same lock before it touches the live
database. The import refuses when it cannot have it ("stop Headroom first");
an app that starts while an import holds it WAITS, saying so in its log, and
boots on the imported collection once the import lets go. The kernel releases
a flock when its holder exits however it exits, so a crash never leaves the
directory locked. It works across containers too: they share the host's
kernel, and the volume is the same file.
"""

from __future__ import annotations

import fcntl
import logging
import os
import time
from pathlib import Path

from headroom.config import settings

logger = logging.getLogger(__name__)

LOCK_NAME = ".headroom.lock"
#: How often a waiting app says it is still waiting.
_WAIT_LOG_SECONDS = 30.0


def lock_path() -> Path:
    """Beside the database and the uploads: `/data/.headroom.lock` in Docker."""
    return settings.upload_dir.parent / LOCK_NAME


def try_acquire() -> int | None:
    """The lock's file descriptor, or None if another process holds it."""
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    except BaseException:
        os.close(fd)
        raise
    return fd


def acquire_waiting(poll: float = 1.0) -> int:
    """Take the lock, waiting as long as it takes and saying why.

    Polled rather than a blocking `flock`, so the wait is logged — an app that
    sits silently at boot looks hung, and this one is waiting on purpose.
    """
    fd = try_acquire()
    waited = 0.0
    next_log = 0.0
    while fd is None:
        if waited >= next_log:
            logger.warning(
                "Waiting for %s: another Headroom process, or a database import, "
                "is using this data directory (%.0fs so far)", lock_path(), waited,
            )
            next_log += _WAIT_LOG_SECONDS
        time.sleep(poll)
        waited += poll
        fd = try_acquire()
    return fd


def release(fd: int | None) -> None:
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
