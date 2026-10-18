"""Import a database from a terminal: `python -m headroom.import_database FILE`.

The same import as Settings → Upkeep → Import a database (`services/
database_import`), for the places a browser is not: setting up a new machine
from an old one's backup (`scripts/setup.sh --import FILE`), or the Docker
install from the host (`scripts/import-database.sh FILE`, which streams the
file in on stdin as `-`, so nothing has to be copied into the volume first).

Run it with the app STOPPED; it refuses otherwise (`instance_lock`: the app
holds the data directory's lock while it runs, and an app started during an
import waits for it). The app's queues live in memory and its workers write
to hats by id, so the two must never run at once; the next boot re-queues
whatever the imported database left pending. `--preview` stages and prints
without changing anything, and may run alongside the app.

    python -m headroom.import_database backups/headroom-backup-<time>.tar.gz
    python -m headroom.import_database --preview old-headroom.db
    python -m headroom.import_database --yes - < headroom-backup-<time>.tar.gz
    python -m headroom.import_database --list
    python -m headroom.import_database --restore-point pre-upgrade-<…>.db

`--list` and `--restore-point` reach the files in `backups/` by name — the
way back when the app itself will not start, without copying one out of a
Docker volume first.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from headroom import database
from headroom.schemas.admin import DatabaseImportPreview
from headroom.services import (
    database_import,
    database_upgrade,
    errors,
    instance_lock,
    upgrade_guard,
)

_CHUNK = 1024 * 1024


async def _stdin() -> AsyncIterator[bytes]:
    while chunk := await asyncio.to_thread(sys.stdin.buffer.read, _CHUNK):
        yield chunk


def _list_restore_points() -> int:
    points = asyncio.run(database_import.restore_points())
    if not points:
        print("No backups in this server's backups folder.")
        return 0
    for p in points:
        print(
            f"{p.name}  {p.kind.value.replace('_', '-'):<11} "
            f"{p.created_at:%Y-%m-%d %H:%M} UTC  {p.size_bytes / (1024 * 1024):,.1f} MB"
        )
    return 0


def _describe(s: DatabaseImportPreview) -> str:
    lines = [
        f"{s.source}: a {'backup archive' if s.kind == 'archive' else 'database file'}"
        + (f", last run by Headroom {s.version}" if s.version else ""),
        f"  {s.hats} hats ({s.disposed_hats} disposed besides), {s.cases} cases, "
        f"{s.rooms} rooms, {s.purchases} purchases, {s.wear_logs} wears",
    ]
    if s.newest_change_at:
        lines.append(f"  newest change: {s.newest_change_at:%Y-%m-%d %H:%M} UTC")
    if s.kind == "archive":
        lines.append(f"  {s.photos_included} photos in the archive")
    if s.photos_missing:
        lines.append(f"  {s.photos_missing} hats would have no photo (not in the file or on this server)")
    if s.degraded:
        lines.append("  this archive was written by the raw-file fallback; it passed the integrity check")
    lines.append(
        (f"It replaces the {s.current_hats} hats here. " if s.current_hats
         else "There are no hats here yet to replace. ")
        + ("This install's account, passkeys, share links, API keys, model and "
           "off-site backup stay as they are."
           if s.keeps_account else "There is no account here yet, so the import's comes too.")
    )
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> int:
    session_factory = database.async_session
    live = upgrade_guard.sqlite_file(database.engine.url)
    # A preview compares against the live collection when there is one. When
    # there is not, it must not open one: connecting creates the file, and
    # the next boot would then snapshot an empty database as an "upgrade".
    compare_with = session_factory if (not args.preview or live is None or live.exists()) else None
    held = None
    if not args.preview:
        # The data directory's lock, held for the whole import: refused while
        # the app runs, and an app started meanwhile waits for it (see
        # `instance_lock`). A preview writes nothing live and needs none.
        held = instance_lock.try_acquire()
        if held is None:
            print(
                f"Not imported: Headroom is running on this data directory (it holds "
                f"{instance_lock.lock_path()}). Stop it first — scripts/import-database.sh "
                "does that for a Docker install.",
                file=sys.stderr,
            )
            await database.engine.dispose()
            return 1
    try:
        if not args.preview:
            # The live database first, the way a boot would (snapshot on a
            # version change, migrate, repair): the swap copies column by
            # column into the CURRENT schema, and on a fresh install this is
            # what creates the file.
            await database_upgrade.upgrade(database.engine, session_factory)
        if args.restore_point:
            summary = await database_import.stage_restore_point(
                args.restore_point, session_factory=compare_with
            )
        elif args.file == "-":
            summary = await database_import.stage_upload(
                _stdin(), filename="stdin", declared_size=None, session_factory=compare_with
            )
        else:
            summary = await database_import.stage_file(
                Path(args.file), session_factory=compare_with
            )
        # Flushed: piped, stdout is buffered and stderr is not, so the "not
        # confirmed" line below printed ABOVE the summary it was about.
        print(_describe(summary), flush=True)
        if args.preview:
            await database_import.discard()
            return 0
        if not args.yes:
            if args.file == "-" or not sys.stdin.isatty():
                print("Not confirmed: add --yes to import without a prompt.", file=sys.stderr)
                await database_import.discard()
                return 2
            answer = await asyncio.to_thread(input, "Replace this collection? [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                print("Nothing changed.")
                await database_import.discard()
                return 1
        result = await database_import.apply(
            summary.token,
            bind=database.engine,
            session_factory=session_factory,
            resume=False,
        )
    except errors.DomainError as exc:
        print(f"Not imported: {exc}", file=sys.stderr)
        await database_import.discard()
        return 1
    finally:
        await database.engine.dispose()
        instance_lock.release(held)
    print(
        f"Imported {result.hats} hats"
        + (f" and {result.photos_restored} photo files" if result.photos_restored else "")
        + f". The previous database is saved as backups/{result.snapshot}."
    )
    print("Start (or restart) Headroom to pick it up.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m headroom.import_database",
        description="Replace this Headroom collection with a backup's.",
    )
    parser.add_argument(
        "file", nargs="?", help='a backup (.tar.gz) or database (.db); "-" reads it from stdin'
    )
    parser.add_argument(
        "--restore-point", metavar="NAME", help="a file in this server's backups folder (see --list)"
    )
    parser.add_argument("--list", action="store_true", help="list the backups this server holds")
    parser.add_argument("--yes", action="store_true", help="import without asking")
    parser.add_argument("--preview", action="store_true", help="show what the file holds; change nothing")
    parser.add_argument("--verbose", action="store_true", help="show the app's log, tracebacks included")
    args = parser.parse_args(argv)
    if not args.list and (args.file is None) == (args.restore_point is None):
        parser.error("give a FILE or --restore-point NAME (one of them)")
    # Quiet by default: every refusal arrives as one plain sentence below,
    # and the service's log lines (a traceback for a failed migration) are
    # for the server log, not a person at a terminal.
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.CRITICAL,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.list:
        return _list_restore_points()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
