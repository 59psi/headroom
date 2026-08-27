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
from datetime import datetime, timezone

from sqlalchemy import select

from headroom.config import env_flag, env_float, env_int
from headroom.models.hat import Hat

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


#: How many hats a MANUAL sweep touches by default. Bounded because the route
#: runs inline: uncapped, ~235 hats at one second apart is a four-minute HTTP
#: request, which on a phone is a dead spinner and then a proxy timeout — after
#: which the result is discarded and nothing is recorded. Ordering is
#: stalest-first, so pressing the button again continues where it stopped.
MANUAL_SWEEP_LIMIT = 50


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
    }


async def _eligible_hats(db, limit: int | None = None) -> list[Hat]:
    """Active hats whose price this task is allowed to move.

    `manual` is excluded HERE as well as inside `refresh_melin_resale`. The
    inner guard makes the write safe; this one makes it free — a protected hat
    should not cost a network round trip to discover it is protected.
    """
    stmt = (
        select(Hat)
        .where(
            Hat.disposed_at.is_(None),
            (Hat.resale_price_scope.is_(None)) | (Hat.resale_price_scope != "manual"),
        )
        .order_by(Hat.resale_checked_at.asc().nulls_first(), Hat.id)
    )
    cap = limit if limit is not None else repricing_batch_limit()
    if cap:
        stmt = stmt.limit(cap)
    return list((await db.execute(stmt)).scalars().all())


async def count_eligible(session_factory=None) -> int:
    """How many hats are still awaiting a sweep.

    Lets a bounded manual run say "50 done, 184 to go" instead of leaving the
    reader to guess whether the button finished the job. A COUNT, never
    `len()` of a capped list — that mistake has been made three times in this
    codebase already (colorway catalog, analysis pending_count, guest search).
    """
    from sqlalchemy import func  # noqa: PLC0415 — local, only this path needs it

    if session_factory is None:
        from headroom.database import async_session  # noqa: PLC0415 — import cycle

        session_factory = async_session

    async with session_factory() as db:
        return int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Hat)
                    .where(
                        Hat.disposed_at.is_(None),
                        (Hat.resale_price_scope.is_(None))
                        | (Hat.resale_price_scope != "manual"),
                    )
                )
            ).scalar_one()
        )


async def reprice_once(session_factory=None, limit: int | None = None) -> tuple[int, int]:
    """One sweep. Returns (repriced, considered). Raises only on a total failure.

    Ordering is oldest-checked-first, so a sweep that is cut short by a
    restart or a batch limit still makes progress on the stalest prices rather
    than re-doing the freshest ones.

    `session_factory` is the seam: the route passes
    `request.app.state.session_factory` (which tests swap for the test DB) and
    the background loop passes the real one. Reaching for the module-level
    `async_session` here instead is the same mistake `error_handler` documents
    — it works in production and silently talks to the wrong database
    everywhere else.
    """
    from headroom.services.hat_analysis_pipeline import refresh_melin_resale

    if session_factory is None:
        from headroom.database import async_session  # noqa: PLC0415 — import cycle

        session_factory = async_session

    delay = repricing_delay_seconds()
    repriced = 0

    # One sweep at a time — see `_sweep_lock`.
    async with _sweep_lock, session_factory() as db:
        hats = await _eligible_hats(db, limit=limit)
        for index, hat in enumerate(hats):
            before = hat.resale_price
            try:
                await refresh_melin_resale(hat)
            except Exception as exc:  # noqa: BLE001 — one hat must not stop the sweep
                logger.info("Re-pricing skipped for hat=%s: %s", hat.id, exc)
            else:
                if hat.resale_price != before:
                    repriced += 1
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
            if delay and index + 1 < len(hats):
                await asyncio.sleep(delay)

    return repriced, len(hats)


async def _loop() -> None:
    interval = repricing_interval_hours() * 3600.0
    logger.info(
        "Re-pricing scheduler started: every %.1f hours, %.1fs between hats",
        repricing_interval_hours(), repricing_delay_seconds(),
    )
    while True:
        try:
            repriced, considered = await reprice_once()
            _health.record_success(repriced, considered, scheduled=True)
            logger.info(
                "Re-pricing sweep done: %s of %s hats changed price", repriced, considered
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the loop must outlive any cycle
            _health.record_failure(exc)
            logger.error("Re-pricing sweep failed: %s", exc)
        await asyncio.sleep(interval)


async def start_repricing() -> asyncio.Task | None:
    """Start the sweep loop. Returns the task so the lifespan can cancel it."""
    if not repricing_enabled():
        logger.info("Re-pricing scheduler disabled (HEADROOM_REPRICING_ENABLED)")
        return None
    return asyncio.create_task(_loop())
