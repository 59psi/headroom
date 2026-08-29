"""Live progress for the long in-process sweeps, so a click isn't a void.

Two buttons in Settings kick off minutes of sequential external calls — "Re-price
now" and the colorway "Refresh from Melin Recap" — and neither could show what it
was doing. The refresh was worse than merely quiet: it returns 202 and its only
record of progress was a log line, so from the page a working harvest and a
button that did nothing looked exactly alike.

One type for both, rather than two counters that drift. The analysis queue is
deliberately NOT built on this: its progress is derived from `hats.analysis_job_id`
and survives a restart, because the worker's work outlives the request. These two
sweeps are the opposite — they run inside this process and die with it.

Process-local by design, the same reasoning `RepricingHealth` documents: the
question is "what is this task doing RIGHT NOW", which has no meaning across a
restart. The durable answers already live in the data — `Hat.resale_checked_at`
for prices, the catalog rows themselves for the harvest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class SweepProgress:
    """How far along one long-running sweep is, right now."""

    #: What this sweep is called, for logs and for the API payload.
    name: str = "sweep"
    running: bool = False
    done: int = 0
    total: int = 0
    #: What it is working on at this instant — the useful half. A bare "37 of
    #: 235" says it is alive; naming the hat says it is not stuck on one.
    label: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    #: Set when the sweep ended badly. Kept AFTER `running` goes false, because
    #: the whole point is to still be readable once the thing has stopped.
    error: str | None = None

    def begin(self, total: int) -> None:
        self.running = True
        self.done = 0
        self.total = max(0, total)
        self.label = None
        self.started_at = datetime.now(timezone.utc)
        self.finished_at = None
        # Cleared on START, not on finish. A previous failure must stay visible
        # until something actually supersedes it.
        self.error = None

    def advance(self, label: str | None = None) -> None:
        """One unit done. Advancing past `total` is capped, never wrapped —
        a bar reading 241/235 reads as a bug in the thing being measured."""
        self.done = min(self.done + 1, self.total) if self.total else self.done + 1
        self.label = label

    def finish(self, error: str | None = None) -> None:
        """Always call this, including on the failure path.

        A sweep that raises and leaves `running` true reads as permanently in
        flight — which is the exact false signal this exists to remove, so
        every caller wraps the body in try/finally rather than trusting the
        happy path.
        """
        self.running = False
        self.finished_at = datetime.now(timezone.utc)
        self.label = None
        if error is not None:
            self.error = error

    def snapshot(self) -> dict:
        """Plain dict for the API layer. `pct` is computed here so the two
        cards that render it cannot disagree about how it rounds."""
        return {
            "running": self.running,
            "done": self.done,
            "total": self.total,
            "label": self.label,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "pct": round(100 * self.done / self.total) if self.total else 0,
        }


def new(name: str) -> SweepProgress:
    return SweepProgress(name=name)
