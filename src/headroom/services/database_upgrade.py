"""Bring a database up to this version — the one sequence every door uses.

Snapshot (when the version changed), migrate, run each one-time data repair
the database has not had, put back re-cuts a dead process left half done, and
only then record the version it is now on. That order is the whole point:

* the snapshot comes BEFORE the first schema change, or it is a copy of the
  migrated database and protects nothing;
* the version is recorded LAST, so a run that dies half-way is retried, with
  its snapshot, on the next attempt instead of being taken for finished.

It used to live in the app's lifespan alone, and that is how it got bypassed.
`scripts/setup.sh` initialized the database itself, with `init_db` and no
snapshot, so a bare-metal upgrade migrated the schema and the boot that
followed snapshotted the already-migrated file — the backup the release notes
promised was taken "before any migration runs" was taken after one. An import
needs the same sequence too: an older backup has to be migrated and repaired
before it can stand in for the live database. One function, so no caller can
run the steps in another order or forget one.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from headroom import database
from headroom.models.hat import Hat
from headroom.schemas.hat import KNOWN_CONSTRUCTIONS
from headroom.services import (
    backup_service,
    hat_analysis_pipeline,
    hat_service,
    purchase_service,
    retail_pricing,
    settings_service,
    upgrade_guard,
    vocabulary,
)

logger = logging.getLogger(__name__)


async def _merge_vocabulary_v1(db: AsyncSession) -> int:
    merged = await vocabulary.merge_case_variants(
        db, Hat.construction, known=KNOWN_CONSTRUCTIONS
    )
    return merged + await vocabulary.merge_case_variants(db, Hat.artist_series)


async def _merge_vocabulary_v2(db: AsyncSession) -> int:
    """v1's merge again, now that the key also folds punctuation — plus colorway.

    `vocabulary`'s key used to fold case and whitespace only, so an install
    that already ran v1 still holds `A-Game` beside `A Game` (and the colorway
    field, canonicalized on write since, was never merged at all). Idempotent,
    so a database v1 already fully merged changes nothing.
    """
    merged = await _merge_vocabulary_v1(db)
    return merged + await vocabulary.merge_case_variants(db, Hat.colorway)


#: The one-time data repairs, in the order they run: (flag, repair, log line).
#: Each runs once per database and is marked done in `app_settings`, so a
#: restart never repeats one — the difference between repairing a collection
#: and re-pricing or renaming it daily. One loop, where there were four
#: hand-copied `if get_setting(...) is None: ...; set_setting(...)` blocks,
#: each free to forget its own flag. The repairs are looked up on their
#: modules at CALL time (the lambdas), so a test that patches one reaches it.
#:
#: Per DATABASE, not per install: an imported backup older than a repair has
#: not had it, whatever the database it replaces had, so an import runs this
#: loop on the incoming copy before it goes live.
ONE_TIME_REPAIRS: tuple[tuple[str, Callable[[AsyncSession], Awaitable[int]], str], ...] = (
    # Collapse case/whitespace variants of the free-text vocabulary fields
    # ("Neon"/"NEON"/"neon" -> one collection). Canonicalization only covers
    # writes, so values that predate it, or arrived by import, need this once.
    ("vocabulary_merged_v1", lambda db: _merge_vocabulary_v1(db),
     "Merged %d case-variant vocabulary value(s)"),
    ("retail_prices_v2", lambda db: retail_pricing.backfill_retail_prices(db),
     "Re-priced %d hat(s) from the melin retail table "
     "(the old prompt anchors were years stale)"),
    ("model_names_split_v1", lambda db: hat_analysis_pipeline.backfill_split_model_names(db),
     "Split a leaked colorway out of %d model name(s) — the tool schema had no "
     "colorway field, so Claude appended it to the one field every match gates on"),
    # Normalize general_color onto the curated palette so the color filter
    # chips behave consistently.
    ("color_names_normalized_v1", lambda db: hat_service.normalize_existing_colors(db),
     "Normalized general_color on %d existing hat colors"),
    ("vocabulary_merged_v2", lambda db: _merge_vocabulary_v2(db),
     "Merged %d spelling-variant vocabulary value(s) (punctuation and colorway)"),
    # A reseller's "(RARE)" / "NEW WITH TAGS" read as part of a receipt
    # colorway before 2.85.1, and copied onto hats by their links.
    ("sales_tag_colorways_v1", lambda db: purchase_service.strip_sales_tag_colorways(db),
     "Took a seller's sales tag off %d purchase colorway(s)"),
)


async def run_one_time_repairs(db: AsyncSession) -> None:
    """Each repair this database has not had yet, flagged done as it finishes."""
    for flag, repair, done_message in ONE_TIME_REPAIRS:
        if await settings_service.get_setting(db, flag) is not None:
            continue
        changed = await repair(db)
        await settings_service.set_setting(db, flag, "done")
        if changed:
            logger.info(done_message, changed)


async def upgrade(
    bind: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    snapshot: bool = True,
) -> Path | None:
    """Bring the database behind `bind` up to the running version.

    Returns the pre-upgrade snapshot's path, or None when none was written
    (same version as last time, a fresh database, or `snapshot=False`).

    `snapshot=False` is for a database nobody is running yet — an import's
    staged copy, whose own original is the thing being kept.
    """
    running = upgrade_guard.running_version()
    written: Path | None = None
    if snapshot:
        # "Take a backup first", done by the app rather than asked of a
        # person: on the first boot of a new version, a copy of the database
        # exactly as the previous version left it, before anything below
        # migrates it (see `upgrade_guard`). Best-effort — a snapshot that
        # fails is logged loudly and the upgrade goes on, because an app that
        # refuses to start over its own safety copy is down for a reason
        # nobody can see, and the nightly archives are still there.
        try:
            written = await asyncio.to_thread(
                upgrade_guard.snapshot_before_upgrade,
                upgrade_guard.sqlite_file(bind.url), backup_service.backup_dir(), running,
            )
        except Exception:  # a failed safety copy must not stop the boot; logged with traceback
            logger.exception("Could not snapshot the database before upgrading to %s", running)
        else:
            if written is not None:
                logger.info("Snapshotted the database before upgrading to %s: %s", running, written)

    await database.init_db(bind=bind, session_factory=session_factory)

    async with session_factory() as db:
        await run_one_time_repairs(db)
        # Every time, not once: a re-cut the last shutdown cut short is left
        # showing its uncut original as "cutting out" forever, and only this
        # moment can tell — nothing is running yet. Before the workers start,
        # so a re-cut queued after boot is never mistaken for a stranded one.
        abandoned = await hat_analysis_pipeline.abandon_interrupted_recuts(db)
        if abandoned:
            logger.info(
                "Put %d hat(s) back on their cutout — a re-cut was interrupted "
                "by the last shutdown", abandoned,
            )
        # Last, after migrations and every repair got through: the version
        # this database is now fully upgraded to. Recorded any earlier, a run
        # that died half-way would be taken for a finished upgrade and the
        # next attempt would skip its snapshot.
        await settings_service.set_setting(db, upgrade_guard.LAST_BOOTED_KEY, running)
    return written
