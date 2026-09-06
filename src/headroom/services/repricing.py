"""Keep appraisals current without re-running vision analysis.

Until this existed, a hat's resale value moved only when that hat was
ANALYZED: `refresh_melin_resale` was called from three places, all inside
`hat_analysis_pipeline`. Nothing re-checked prices on a schedule. On the real
deployment that meant every appraisal sat frozen at the date of the last bulk
re-analysis — weeks — and the only way to move them was to re-analyze the whole
collection, spending a Claude vision call per hat purely to fetch a marketplace
median that needs no Claude at all.

Worse, it coupled two unrelated failures: when the Anthropic balance ran out,
Claude raised, the pipeline fell back and returned early, and the price refresh
below it never ran. Prices stopped because *identification* stopped, though
pricing never depended on it.

So this is deliberately independent of analysis. `fetch_resale_stats` keys on
the hat's own `style`, `model_name`, `condition` and `size` — all already in
the database — so re-pricing needs no photo, no API key, and no vision call.

What it will not touch:
  * disposed hats — they have left the collection
  * `resale_price_scope == "manual"` — an owner's own number outranks a
    scraped median. `refresh_melin_resale` enforces this too; it is ALSO
    filtered in the query so a protected hat costs no API call at all.

Failure is per-hat and non-fatal, like every other best-effort path here: one
unreachable listing must not stop the other 234. Health is recorded so a
silently dead re-pricer is visible, which is the whole lesson of the backup
scheduler — an inventory of prices cannot distinguish "nothing changed" from
"nothing ran".
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from headroom.config import env_flag, env_float, env_int
from headroom.models.hat import Hat, ResaleScope
from headroom.services import hat_analysis_pipeline
from headroom.services.melin_recap import MelinRecapError
from headroom.services import sweep_progress

logger = logging.getLogger(__name__)


def repricing_enabled() -> bool:
    return env_flag("HEADROOM_REPRICING_ENABLED")


def repricing_interval_hours() -> float:
    """How often to sweep. Marketplace medians move over days, not minutes."""
    return max(env_float("HEADROOM_REPRICING_INTERVAL_HOURS", 24.0), 0.25)


def repricing_delay_seconds() -> float:
    """Pause between hats.

    A sweep is a few hundred sequential calls to somebody else's public API.
    Spacing them is basic courtesy and also the difference between a background
    task and something that looks like abuse from the far end.
    """
    return max(env_float("HEADROOM_REPRICING_DELAY_SECONDS", 1.0), 0.0)


def repricing_batch_limit() -> int:
    """Most hats to re-price in one sweep. 0 means no cap."""
    return max(env_int("HEADROOM_REPRICING_BATCH_LIMIT", 0), 0)


@dataclass
class RepricingHealth:
    """Is the re-pricer working, and what did it last manage?

    Process-local, and correctly so — unlike the backup upload record, the
    question here is "is this task alive now". The durable answer already
    exists in the data: `Hat.resale_checked_at` is a per-hat timestamp, so how
    stale the prices are is always readable from the hats themselves.
    """

    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    last_repriced: int = 0
    last_considered: int = 0
    #: Hats the last sweep could not consult the marketplace about. Non-zero
    #: with a success is a partial outage; equal to `last_considered` is a
    #: failed sweep (and recorded as one).
    last_unreachable: int = 0

    def record_success(self, repriced: int, considered: int, *, scheduled: bool) -> None:
        """A sweep finished. `scheduled` decides whether it clears the alarm.

        A MANUAL run must not clear `last_error` or `consecutive_failures`.
        Those belong to the scheduler, and a sweep that has failed nightly for
        a month would otherwise read "swept just now, 0 failures" after one
        click of "Re-price now" — hiding precisely the dead-task condition this
        record exists to expose. Clicking a button proves the code works; it
        proves nothing about the background loop.
        """
        now = datetime.now(timezone.utc)
        self.last_run_at = now
        self.last_success_at = now
        self.last_repriced = repriced
        self.last_considered = considered
        if scheduled:
            self.last_error = None
            self.consecutive_failures = 0

    def record_failure(self, reason: Exception | str) -> None:
        self.last_run_at = datetime.now(timezone.utc)
        self.last_error = (
            f"{type(reason).__name__}: {reason}" if isinstance(reason, Exception)
            else str(reason)
        )[:500]
        self.consecutive_failures += 1


_health = RepricingHealth()

#: One sweep at a time, process-wide. The scheduled loop and the manual
#: "Re-price now" button are separate entry points into the same few-hundred
#: sequential calls against somebody else's public API, and nothing otherwise
#: stops them overlapping — or stops two clicks doing so. Pacing each sweep
#: politely while allowing two to run at once would be a courtesy that only
#: looks like one. Single-process by design (see CLAUDE.md), so an in-memory
#: lock is sufficient.
_sweep_lock = asyncio.Lock()

#: Is a FULL sweep queued or running? Distinct from `progress.running`, and the
#: distinction is the whole point.
#:
#: `progress.begin()` fires inside `reprice_once`, AFTER the sweep lock is taken
#: and the eligible-hat query has run — and a BackgroundTask does not start
#: until the response has been sent. So a route guarding on `progress.running`
#: has a window in which a sweep is queued but invisible: two quick presses both
#: read False, both schedule, and both run a full uncapped pass, serialized by
#: `_sweep_lock` into twice the work. Exactly what the guard promised to refuse.
#:
#: Claimed SYNCHRONOUSLY in the request handler instead. The event loop cannot
#: interleave between the check and the set (there is no await between them), so
#: this is atomic without a lock, and it is released by the task's `finally`.
_full_sweep_claimed = False


def claim_full_sweep() -> bool:
    """Reserve the full-sweep slot. False when one is already queued or running.

    Check-and-set with no await between the two, so a second request cannot
    land in the middle of it.

    **Every full sweep claims — the scheduler as well as the button.** Written
    for two presses of one button, this originally asked only what that button
    did and never what else takes `_sweep_lock`. `_loop()` does, for minutes,
    every cycle, unattended: while it ran the slot read free, so "Re-price all"
    would start a second full pass and "Re-price now" would skip its 409 and
    block on the lock for the whole nightly run. A guard that only one of three
    callers respects is not a guard.
    """
    global _full_sweep_claimed
    if _full_sweep_claimed:
        return False
    _full_sweep_claimed = True
    return True


def release_full_sweep() -> None:
    """Free the slot. Must run in a `finally` — a sweep that raised and never
    released would refuse every later press for the life of the process."""
    global _full_sweep_claimed
    _full_sweep_claimed = False


def full_sweep_in_flight() -> bool:
    """Whether a full sweep is queued or running, for callers that must not
    block behind one."""
    return _full_sweep_claimed


#: How many hats a MANUAL sweep touches by default. Bounded because the route
#: runs inline: uncapped, ~235 hats at one second apart is a four-minute HTTP
#: request, which on a phone is a dead spinner and then a proxy timeout — after
#: which the result is discarded and nothing is recorded. Ordering is
#: stalest-first, so pressing the button again continues where it stopped.
MANUAL_SWEEP_LIMIT = 50


#: Live progress of the sweep in flight. Complements `_health`, which answers
#: "did the last one work"; this answers "is one happening right now, and how
#: far along". Both process-local, for the reason RepricingHealth documents.
progress = sweep_progress.SweepProgress()


def health() -> RepricingHealth:
    return _health


def status() -> dict:
    """Read-only snapshot for the admin API."""
    return {
        "enabled": repricing_enabled(),
        "interval_hours": repricing_interval_hours(),
        "last_run_at": _health.last_run_at,
        "last_success_at": _health.last_success_at,
        "last_error": _health.last_error,
        "consecutive_failures": _health.consecutive_failures,
        "last_repriced": _health.last_repriced,
        "last_considered": _health.last_considered,
        "last_unreachable": _health.last_unreachable,
        "progress": progress.snapshot(),
    }


def _eligibility_filters(stale_before: datetime | None) -> list:
    """Which hats a sweep may touch — THE definition, read by the sweep and by
    `count_eligible`. The count used to restate these three clauses by hand,
    so `remaining` was computed from a second copy of the rule that decides
    what a press will do."""
    filters = [
        Hat.disposed_at.is_(None),
        (Hat.resale_price_scope.is_(None)) | (Hat.resale_price_scope != ResaleScope.MANUAL),
    ]
    if stale_before is not None:
        filters.append(Hat.resale_checked_at.is_(None) | (Hat.resale_checked_at < stale_before))
    return filters


async def _eligible_hats(
    db, limit: int | None = None, *, stale_before: datetime | None = None
) -> list[Hat]:
    """Active hats whose price this task is allowed to move.

    `manual` is excluded HERE as well as inside `refresh_melin_resale`. The
    inner guard makes the write safe; this one makes it free — a protected hat
    should not cost a network round trip to discover it is protected.

    `stale_before` narrows to hats not checked since then (never-checked hats
    always qualify). The scheduler passes it; the buttons do not.
    """
    stmt = (
        select(Hat)
        .where(*_eligibility_filters(stale_before))
        .order_by(Hat.resale_checked_at.asc().nulls_first(), Hat.id)
    )
    cap = limit if limit is not None else repricing_batch_limit()
    if cap:
        stmt = stmt.limit(cap)
    return list((await db.execute(stmt)).scalars().all())


async def count_eligible(session_factory=None, *, stale_before=None) -> int:
    """How many hats are still awaiting a sweep.

    Lets a bounded manual run say "50 done, 184 to go" instead of leaving the
    reader to guess whether the button finished the job. A COUNT, never
    `len()` of a capped list — that mistake has been made three times in this
    codebase already (colorway catalog, analysis pending_count, guest search).

    `stale_before` is what makes the number mean "still to do". Without it this
    counted every eligible hat in the collection, so the figure was identical
    before and after a run and `remaining` never decreased — pressing the
    button fifty times reported the same 234 outstanding, which reads as a
    button that does nothing. The sweep stamps `resale_checked_at` on EVERY
    attempt (including the ones it cannot price), so "checked before this run
    started, or never" is exactly the set a further press would visit.
    """
    if session_factory is None:
        from headroom.database import async_session  # noqa: PLC0415 — import cycle

        session_factory = async_session

    async with session_factory() as db:
        return int(
            (
                await db.execute(
                    select(func.count()).select_from(Hat).where(*_eligibility_filters(stale_before))
                )
            ).scalar_one()
        )


async def reprice_once(
    session_factory=None, limit: int | None = None, *, stale_before: datetime | None = None,
) -> tuple[int, int]:
    """One sweep. Returns (repriced, considered). Raises only on a total failure.

    Ordering is oldest-checked-first, so a sweep that is cut short by a
    restart or a batch limit still makes progress on the stalest prices rather
    than re-doing the freshest ones.

    `stale_before` is the scheduler's staleness gate: only hats not checked
    since then are swept. Without it the loop re-priced the WHOLE shelf on
    every boot — a restart loop meant ~235 marketplace calls at 1 s spacing per
    restart, against somebody else's public API, for prices checked minutes
    earlier. `backup_service` has skipped its startup run when a recent backup
    exists since 2.26; this is the same courtesy. `resale_checked_at` already
    answers "is this stale", so the gate is a WHERE clause, not a timer.

    `session_factory` is the seam: the route passes
    `request.app.state.session_factory` (which tests swap for the test DB) and
    the background loop passes the real one. Reaching for the module-level
    `async_session` here instead is the same mistake `error_handler` documents
    — it works in production and silently talks to the wrong database
    everywhere else.
    """
    if session_factory is None:
        from headroom.database import async_session  # noqa: PLC0415 — import cycle

        session_factory = async_session

    delay = repricing_delay_seconds()

    # One sweep at a time — see `_sweep_lock`.
    async with _sweep_lock, session_factory() as db:
        hats = await _eligible_hats(db, limit=limit, stale_before=stale_before)
        # try/finally, not a happy-path call at the bottom: a sweep that raises
        # and leaves `running` true reads as permanently in flight, which is
        # the exact false signal the progress record exists to remove.
        progress.begin(len(hats))
        # try/FINALLY, with the error recorded in `except`. An `except
        # Exception` alone does not catch CancelledError, which is a
        # BaseException — and the blocking POST behind "Re-price now" runs for
        # ~50s, so a phone disconnecting mid-sweep left `running` true forever
        # and the card polling a phantom sweep every 2s. That is the exact
        # false signal this record exists to remove.
        error: str | None = None
        try:
            return await _sweep(db, hats, delay)
        except Exception as exc:
            error = str(exc)[:300]
            raise
        finally:
            progress.finish(error=error)


async def _sweep(db, hats: list, delay: float) -> tuple[int, int]:
    """The loop itself, split out so `reprice_once` owns only the bookkeeping."""
    repriced = 0
    unreachable = 0
    for index, hat in enumerate(hats):
        before = hat.resale_price
        # Plain columns for the label. `display_id` would resolve fine —
        # `Hat.case` is `lazy="selectin"`, so there is no lazy-load hazard here
        # (a previous version of this comment claimed one) — but a per-hat
        # progress label has no use for a shelf slot.
        progress.start_unit(hat.model_name or f"Hat #{hat.id}")
        try:
            # Module attribute, looked up at CALL time: the tests (and the
            # scheduler tests especially) stub `hat_analysis_pipeline.
            # refresh_melin_resale`, and a `from … import` bound at import time
            # would have kept calling the real one. This was a function-local
            # import for that reason; the attribute lookup keeps the late
            # binding with the import where imports belong.
            outcome = await hat_analysis_pipeline.refresh_melin_resale(hat)
        except Exception as exc:  # noqa: BLE001 — one hat must not stop the sweep
            logger.info("Re-pricing skipped for hat=%s: %s", hat.id, exc)
            outcome = hat_analysis_pipeline.RESALE_UNREACHABLE
        else:
            if hat.resale_price != before:
                repriced += 1
        if outcome == hat_analysis_pipeline.RESALE_UNREACHABLE:
            # The marketplace was not consulted, so nothing was checked:
            # no stamp. Stamping here pushed every hat a dead marketplace
            # skipped to the BACK of the oldest-first queue, behind hats that
            # had actually been priced.
            unreachable += 1
            progress.advance()
            if delay and index + 1 < len(hats):
                await asyncio.sleep(delay)
            continue
        # Stamp the attempt WHETHER OR NOT it produced a price.
        #
        # `refresh_melin_resale` only sets `resale_checked_at` on the path
        # that finds listings; it returns early for a non-melin brand, an
        # API error, or an empty result. Those hats therefore keep a NULL
        # timestamp forever, and since the query orders `nulls_first` they
        # permanently own the head of the queue — a capped sweep would
        # re-visit the same never-priceable rows every cycle and never
        # reach the rest. The column means "when the marketplace was last
        # checked for this hat", which is exactly what this records.
        #
        # Safe against `price_audit`, whose `was_market_priced` hint reads
        # this field: that report covers only `manual`-scope hats, which
        # this sweep excludes outright.
        hat.resale_checked_at = datetime.now(timezone.utc)
        # Commit as we go. A sweep is minutes long; holding every change to
        # the end means a restart in the middle throws all of it away.
        await db.commit()
        progress.advance()
        if delay and index + 1 < len(hats):
            await asyncio.sleep(delay)

    _health.last_unreachable = unreachable
    if hats and unreachable == len(hats):
        # Every lookup failed: a dead marketplace, not a flat market. The
        # two used to be indistinguishable — `record_success`, `last_error`
        # null, "0 of 234 hats changed price" — so the sweep now fails the
        # way its own bookkeeping expects a failure to look.
        raise MelinRecapError(
            f"the marketplace was unreachable for all {unreachable} hats swept"
        )
    return repriced, len(hats)


async def _loop(session_factory=None) -> None:
    interval = repricing_interval_hours() * 3600.0
    logger.info(
        "Re-pricing scheduler started: every %.1f hours, %.1fs between hats",
        repricing_interval_hours(), repricing_delay_seconds(),
    )
    while True:
        # The scheduled sweep claims the SAME slot the button does, and that is
        # a correctness fix rather than tidiness. The claim was added for two
        # quick presses of "Re-price all" and asked only what that button does
        # — never what else takes `_sweep_lock`. This loop does, for minutes at
        # a time, every cycle, unattended. While it ran, `full_sweep_in_flight()`
        # answered False and both routes lied: "Re-price all" started a second
        # full pass (the one thing it promises to refuse) and "Re-price now"
        # skipped its 409 and blocked on the lock for the whole nightly run —
        # the dead spinner and proxy timeout its own cap exists to prevent.
        # The sweep nobody watches was the sweep nothing accounted for.
        if not claim_full_sweep():
            # A manual full sweep holds the slot. It covers the same shelf this
            # cycle would, so skipping loses nothing, where queueing behind it
            # would run those minutes twice.
            logger.info("Re-pricing sweep skipped: a full sweep is already running")
        else:
            try:
                # Only what is DUE: a hat checked within one interval is left
                # alone, so a restart does not re-run a sweep that just finished.
                due_before = datetime.now(timezone.utc) - timedelta(seconds=interval)
                repriced, considered = await reprice_once(
                    session_factory, stale_before=due_before
                )
                _health.record_success(repriced, considered, scheduled=True)
                logger.info(
                    "Re-pricing sweep done: %s of %s hats changed price", repriced, considered
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — the loop must outlive any cycle
                _health.record_failure(exc)
                logger.error("Re-pricing sweep failed: %s", exc)
            finally:
                # `finally`, not the happy path: CancelledError is a
                # BaseException and re-raised above, and a canceled scheduler
                # that kept the slot would refuse every later press.
                release_full_sweep()
        await asyncio.sleep(interval)


async def start_repricing(session_factory=None) -> asyncio.Task | None:
    """Start the sweep loop. Returns the task so the lifespan can cancel it."""
    if not repricing_enabled():
        logger.info("Re-pricing scheduler disabled (HEADROOM_REPRICING_ENABLED)")
        return None
    return asyncio.create_task(_loop(session_factory))
