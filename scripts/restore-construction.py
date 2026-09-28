#!/usr/bin/env python3
"""Restore hat `construction` values from a backup tarball.

Why this exists: for a window in 2.11.0, photo analysis was allowed to
overwrite a construction the owner had typed. It reads HYDRO and HYDROLite off
a single photo unreliably — the distinguishing features are bonded seams, a
gel-welded logo and a sweatband, none of which reliably survive a front-on shot
— so "correcting" often meant replacing a right answer from the person holding
the hat with a wrong one from a picture. 2.12.0 stopped the overwrite and a
later release stopped analysis writing construction at all — it is owner-only
now (`_apply_construction` is a no-op) — but neither undoes what already
happened, and the audit log of the time recorded only WHICH fields changed, not
their previous values.

The backups do hold those values. This reads a backup's database, compares its
`construction` column against the live one, and restores the differences.

Usage — Docker. The script is not in the image, and `/data` is a named volume
the host cannot see as a path, so feed the script to the CONTAINER's Python on
stdin; inside it, `/data` is where the backups and the database are:

    # See what would change — reads only, writes nothing:
    docker compose exec -T headroom python - \\
        /data/backups/headroom-backup-<timestamp>.tar.gz < scripts/restore-construction.py

    # Apply it:
    docker compose exec -T headroom python - \\
        /data/backups/headroom-backup-<timestamp>.tar.gz --apply < scripts/restore-construction.py

Usage — bare metal, from the project root (backups sit beside `./uploads`):

    uv run python scripts/restore-construction.py backups/headroom-backup-<timestamp>.tar.gz
    uv run python scripts/restore-construction.py backups/headroom-backup-<timestamp>.tar.gz --apply

The live database defaults to the one the app itself is configured with —
`HEADROOM_DATABASE_URL`, resolved exactly as the backup code resolves it — so
the same command is right in both places. It used to be a hardcoded
`/data/headroom.db`, which is wrong on bare metal and, on Docker, a path only
the container has. `--db` overrides it.

Pick a backup from BEFORE the values were overwritten. `--apply` rewrites
`construction`, re-derives `hydro`/`hydrolite` from it and records the value as
the owner's (`construction_source`, so the construction audit's bulk clear
leaves it alone), matching `Hat.set_construction()`. Hats absent from the backup, and hats whose backup
value was empty, are left alone: a blank in the backup means "not stated then",
which is not a reason to erase something stated since.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path

try:
    # The app's own resolution of its database path — the container's Python
    # and `uv run` both have the package, and asking it beats a second copy of
    # the rule that has to be kept in step.
    from headroom.services import backup_service
except ImportError:  # a Python without the app installed: --db is then required
    backup_service = None


def _default_db() -> Path | None:
    """The database the app is configured with, or None if it cannot be told."""
    if backup_service is None:
        return None
    return backup_service._db_path()


#: `construction_audit.OWNER_SOURCE`, restated because this script also runs
#: on a Python without the app installed; the test file pins the two together.
_OWNER_SOURCE = "owner"


def _derive_flags(value: str | None) -> tuple[bool, bool]:
    """Mirror of `Hat.set_construction` — HYDROLite first, it contains 'hydro'."""
    key = (value or "").strip().lower().replace("-", "").replace(" ", "")
    hydrolite = "hydrolite" in key
    return hydrolite, ("hydro" in key and not hydrolite)


def _extract_db(archive: Path, into: Path) -> Path:
    """Pull the .db (and its WAL sidecar, if any) out of a backup tarball."""
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        member = next((m for m in members if m.name.endswith(".db") and m.isfile()), None)
        if member is None:
            sys.exit(f"No .db file found inside {archive}")
        # `endswith`, not `== "DEGRADED-BACKUP-README.txt"`: the archive stores
        # it as `data/DEGRADED-BACKUP-README.txt`, so the equality check never
        # matched and the torn-backup warning never fired.
        if any(m.name.endswith("DEGRADED-BACKUP-README.txt") for m in members):
            print("!! This backup was taken with the raw-file fallback and may be torn.")
            print("!! Verify it before trusting the values below.\n")
        tar.extract(member, path=into, filter="data")
        # The WAL fallback archives the -wal beside the .db; without it SQLite
        # opens the main file and misses every transaction still in the log.
        for sidecar in members:
            if sidecar.isfile() and sidecar.name.endswith((".db-wal", ".db-shm")) \
                    and sidecar.name.startswith(member.name[: -len(".db")]):
                tar.extract(sidecar, path=into, filter="data")
    return into / member.name


def main() -> None:
    default_db = _default_db()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("archive", type=Path, help="Path to a headroom-backup-*.tar.gz")
    ap.add_argument(
        "--db", type=Path, default=default_db,
        help=f"Live DB (default: the app's configured database, {default_db or 'unresolved'})",
    )
    ap.add_argument("--apply", action="store_true", help="Actually write the changes")
    args = ap.parse_args()

    if not args.archive.is_file():
        sys.exit(f"No such backup: {args.archive}")
    if args.db is None:
        sys.exit("Could not work out the app's database — pass --db PATH.")
    if not args.db.is_file():
        sys.exit(f"No such database: {args.db}")

    # Extracted beside the archive, not into the system temp dir: in the
    # container that is a RAM tmpfs charged to the app's memory limit, and the
    # archive's own directory is the data volume.
    with tempfile.TemporaryDirectory(prefix="headroom-restore-", dir=args.archive.parent) as tmp:
        old_db = _extract_db(args.archive, Path(tmp))

        old = sqlite3.connect(f"file:{old_db}?mode=ro", uri=True)
        try:
            was = dict(old.execute("SELECT id, construction FROM hats"))
        except sqlite3.OperationalError:
            sys.exit(
                "That backup predates the `construction` column — it has nothing "
                "to restore. Use a backup taken after upgrading to 2.11.0."
            )
        finally:
            old.close()

        live = sqlite3.connect(args.db)
        try:
            now = dict(live.execute("SELECT id, construction FROM hats"))

            changes = [
                (hat_id, now.get(hat_id), was[hat_id])
                for hat_id in sorted(was)
                # Only where the backup HAS a value and the live DB disagrees.
                if was[hat_id] and hat_id in now and (now[hat_id] or "") != was[hat_id]
            ]

            if not changes:
                print("Nothing to restore — every construction already matches the backup.")
                return

            print(f"{len(changes)} hat(s) differ from {args.archive.name}:\n")
            for hat_id, current, original in changes:
                print(f"  hat {hat_id:>4}:  {current or '(empty)'!r:>24}  ->  {original!r}")

            if not args.apply:
                print("\nDry run. Re-run with --apply to write these back.")
                return

            # `construction_source` is the provenance `Hat.set_construction`
            # keeps beside the value, and the construction audit's bulk clear
            # leaves an OWNER's value alone by it. A restored value is the
            # owner's — that is this script's whole premise — and applying it
            # is their own decision, made after reading the preview above, the
            # same footing as a replacement picked in the audit. Left alone,
            # the column went on describing the value it REPLACED: a restore
            # over an analyzer's guess stayed unprotected from the next sweep.
            # Only where the column exists, so a database not yet migrated by
            # a 2.81+ boot is still restorable.
            has_source = any(
                row[1] == "construction_source"
                for row in live.execute("PRAGMA table_info(hats)")
            )
            for hat_id, _current, original in changes:
                hydrolite, hydro = _derive_flags(original)
                if has_source:
                    live.execute(
                        "UPDATE hats SET construction = ?, construction_source = ?, "
                        "hydrolite = ?, hydro = ? WHERE id = ?",
                        (original, _OWNER_SOURCE, int(hydrolite), int(hydro), hat_id),
                    )
                else:
                    live.execute(
                        "UPDATE hats SET construction = ?, hydrolite = ?, hydro = ? WHERE id = ?",
                        (original, int(hydrolite), int(hydro), hat_id),
                    )
            live.commit()
            print(f"\nRestored {len(changes)} hat(s). Restart Headroom to pick them up.")
        finally:
            live.close()


if __name__ == "__main__":
    main()
