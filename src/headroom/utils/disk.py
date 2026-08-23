"""How much room is left on the volume everything shares.

The database and its WAL, every uploaded photo and its four derivatives, and
seven rolling backup tarballs of all of the above live on one SD card. Until
this module existed nothing in the app could see that card filling up:
`/health/ready` proved the uploads directory was writable by writing two
bytes, and two bytes fit on a volume with 8 KB free — while a 200 MB backup
tarball does not, SQLite raises `disk I/O error`, and photo uploads stop.

A write probe answers "is this mounted and writable". It cannot answer "is
there room to keep going". Those are different questions whose failures look
identical right up until the moment they don't.

Two thresholds, because there are two different things to say:

    ``low``      running out — logged and surfaced, still serving
    ``not ok``   out — readiness fails, which is the only signal this app has
                 that reaches Docker without anyone logging in

The critical floor is an absolute byte count rather than a share of the disk,
because what matters is whether the next backup can be written and that is a
size, not a percentage. A 5% floor reserves 25 GB nobody needs on a 512 GB
disk, and on a 16 GB card it fires far too late to act on.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from headroom.config import env_float, env_int

#: Below this share of the volume, say so. A warning only: the app keeps
#: working, and the entire point is being told while there is still time.
DEFAULT_WARN_PCT = 15.0

#: Below this many megabytes free, readiness fails. Sized to clear one backup
#: tarball plus the working room `tar` wants — on the reasoning that the last
#: thing you want to stop working on a filling disk is the backup.
DEFAULT_MIN_FREE_MB = 500


def warn_pct() -> float:
    """Warning threshold, as a percentage of the volume. Live-read."""
    return env_float("HEADROOM_DISK_WARN_PCT", DEFAULT_WARN_PCT)


def min_free_mb() -> int:
    """Hard floor in megabytes, below which readiness fails. Live-read."""
    return env_int("HEADROOM_DISK_MIN_FREE_MB", DEFAULT_MIN_FREE_MB)


@dataclass(frozen=True)
class DiskStatus:
    """A point-in-time reading of one volume."""

    ok: bool
    """False once free space is under the hard floor — gates readiness."""

    low: bool
    """True under the warning threshold. Still serving, but say so."""

    free_bytes: int
    total_bytes: int
    error: str | None = None

    @property
    def free_pct(self) -> float:
        if not self.total_bytes:
            return 0.0
        return round(self.free_bytes / self.total_bytes * 100, 1)

    @property
    def free_mb(self) -> int:
        return self.free_bytes // (1024 * 1024)

    def summary(self) -> str:
        """One line for a log. Says the number AND the threshold it crossed."""
        if self.error:
            return f"disk space unknown ({self.error})"
        return (
            f"{self.free_mb:,} MB free ({self.free_pct}% of "
            f"{self.total_bytes // (1024 * 1024):,} MB)"
        )


def check(path: Path) -> DiskStatus:
    """Free space on the volume holding `path`.

    A failure to stat the volume reports `ok=True`. This is a health *signal*,
    and a signal that takes the app down when its own measurement breaks is
    worse than no signal at all — but the error travels with the reading, so
    an authenticated caller can see why the numbers are missing rather than
    reading a confident zero.
    """
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        return DiskStatus(
            ok=True, low=False, free_bytes=0, total_bytes=0, error=str(exc)
        )

    free_mb = usage.free / (1024 * 1024)
    pct = (usage.free / usage.total * 100) if usage.total else 0.0
    return DiskStatus(
        ok=free_mb >= min_free_mb(),
        low=pct < warn_pct(),
        free_bytes=usage.free,
        total_bytes=usage.total,
    )
