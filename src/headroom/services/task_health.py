"""Is a background loop actually working, or merely still scheduled?

Every unattended loop in this app has the same blind spot: nobody is watching
while it runs, and its output cannot distinguish "nothing to do" from "died
weeks ago". `backup_service.BackupHealth` and `repricing.RepricingHealth` each
answer that for themselves. `_prune_loop` — the only thing bounding
`activity_log` and `auth_sessions` growth — answered it for nobody, logging one
WARNING per day into a container log while both tables grew on an SD card.

**Deliberately not a base class for the other two.** They look similar and are
not: `RepricingHealth.record_success` takes `scheduled` because a manual run
must NOT clear an alarm the nightly sweep raised, and `BackupHealth` persists
its upload half to disk because that half answers a question about the world
rather than about this process. Both distinctions were learned from real
failures and are written down where they apply. Hoisting the four fields they
happen to share would put pressure on those differences to be flattened into
the shared thing, which is the failure `catalog_service._by_scarcity` records
in reverse — a shape kept alive past its meaning. A third caller is not enough
evidence for an abstraction that would have to carry three sets of exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class TaskHealth:
    """The outcome of the last few attempts by one periodic task."""

    #: For log lines and the API payload — "retention prune", "thumbnails".
    name: str = "task"
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    #: What the last successful attempt actually did. A count of work DONE, not
    #: of items looked at: a sweep that examines a thousand rows and removes
    #: none is a working sweep, and reporting the visit count would make an
    #: idle system look busy while looking identical to one silently failing.
    last_result: int = 0

    def record_success(self, result: int = 0) -> None:
        now = datetime.now(timezone.utc)
        self.last_attempt_at = now
        self.last_success_at = now
        self.last_result = result
        self.last_error = None
        self.consecutive_failures = 0

    def record_failure(self, reason: Exception | str) -> None:
        """Advance the attempt clock and raise the alarm.

        Accepts a plain string as well as an exception, for the same reason
        `BackupHealth.record_failure` does: the likeliest failure arrives as a
        return value that was checked rather than something that was raised,
        and a signature accepting only exceptions quietly pushes callers toward
        reporting those as successes.
        """
        self.last_attempt_at = datetime.now(timezone.utc)
        self.last_error = (
            f"{type(reason).__name__}: {reason}" if isinstance(reason, Exception)
            else str(reason)
        )[:500]
        self.consecutive_failures += 1

    def snapshot(self) -> dict:
        """Plain dict for the API layer."""
        return {
            "name": self.name,
            "last_attempt_at": (
                self.last_attempt_at.isoformat() if self.last_attempt_at else None
            ),
            "last_success_at": (
                self.last_success_at.isoformat() if self.last_success_at else None
            ),
            "last_error": self.last_error,
            "consecutive_failures": self.consecutive_failures,
            "last_result": self.last_result,
        }
