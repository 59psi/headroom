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

    def record_success(self, repriced: int, considered: int) -> None:
        now = datetime.now(timezone.utc)
        self.last_run_at = now
        self.last_success_at = now
        self.last_error = None
        self.consecutive_failures = 0
        self.last_repriced = repriced
        self.last_considered = considered

    def record_failure(self, reason: Exception | str) -> None:
        self.last_run_at = datetime.now(timezone.utc)
        self.last_error = (
            f"{type(reason).__name__}: {reason}" if isinstance(reason, Exception)
            else str(reason)
        )[:500]
        self.consecutive_failures += 1


_health = RepricingHealth()


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


async def _eligible_hats(db) -> list[Hat]:
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
    limit = repricing_batch_limit()
    if limit:
        stmt = stmt.limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def reprice_once(session_factory=None) -> tuple[int, int]:
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

    async with session_factory() as db:
        hats = await _eligible_hats(db)
        for index, hat in enumerate(hats):
            before = hat.resale_price
            try:
                await refresh_melin_resale(hat)
            except Exception as exc:  # noqa: BLE001 — one hat must not stop the sweep
                logger.info("Re-pricing skipped for hat=%s: %s", hat.id, exc)
                continue
            if hat.resale_price != before:
                repriced += 1
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
            _health.record_success(repriced, considered)
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
