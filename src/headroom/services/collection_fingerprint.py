"""Has the COLLECTION changed? — the question the backup gate asks of the database.

The scheduled backup writes an archive only when something changed since the
last one, so a fixed-size window of archives spans as much history as the
collection took to change that many times. It answered "changed" from the
database FILE — the size and mtime of `headroom.db` and its WAL — and the file
moves on writes that change nothing anyone would restore:

* the nightly re-pricing sweep stamps `resale_checked_at` on every hat it
  consults, and commits, even when no price moved;
* a clean shutdown checkpoints the WAL into the main file, which rewrites both;
* the retention prune deletes old audit rows and expired sessions every day;
* a login writes a session row and an audit row, and a passkey login bumps the
  credential's `sign_count`.

Measured: with re-pricing on (the default) every daily cycle wrote a full
tarball, and a stop/start with no activity at all wrote another. KEEP=5 then
covered five DAYS rather than five changes — each "restatement of the newest
one" evicting a real historical snapshot, the pattern the gate exists to stop.

So this digests the ROWS instead: every mapped table's content, minus the
tables and columns that are the app's own bookkeeping. A checkpoint moves no
rows; a sweep that re-priced nothing changes only excluded columns (the
consult stamp, and the listing count the price's label quotes); a price that
DID move changes `resale_price`, which is included. Reading a few
thousand rows is milliseconds, cheap beside the tarball it decides about.

Synchronous on purpose: the gate runs in a worker thread, and this opens its
own read-only engine rather than borrowing the app's async one. Statements are
built from the models' metadata, so no SQL is assembled from strings.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import create_engine, select

from headroom.database import Base
from headroom.models import __all_models__

# Imported for its side effect: every model registered on `Base.metadata`, so
# the digest covers every table the app declares, not only the ones some
# earlier import happened to load.
_ = __all_models__

#: Tables whose rows record what the APP did rather than what the collection
#: holds. They are still in every archive — the backup copies the whole file —
#: they just do not, on their own, make a new archive worth writing: an audit
#: row or a session appears with every login and disappears with every prune.
EXCLUDED_TABLES: frozenset[str] = frozenset({
    "activity_log",
    "auth_sessions",
    "analysis_jobs",
    "import_jobs",
    "import_job_items",
})

#: Columns rewritten on rows whose content did not change. Everything else in
#: a table is content, including the prices a sweep does move.
EXCLUDED_COLUMNS: dict[str, frozenset[str]] = {
    # "When the marketplace was last asked" — stamped on every consult,
    # whatever the answer. And the resale price's source LABEL, which the
    # same consult rewrites with the listing count ("median of 8 live …
    # listings"): that count moves with every listing that comes or goes on a
    # live marketplace, median unchanged, so a sweep that moved no price still
    # opened the gate most nights. The price and its scope are content and
    # stay in; a moved price is a change.
    "hats": frozenset({"resale_checked_at", "ebay_checked_at", "resale_price_source"}),
    # A counter every passkey login increments.
    "passkey_credentials": frozenset({"sign_count"}),
}

#: `updated_at` is an `onupdate=now()` stamp wherever it appears, so it moves
#: with any UPDATE — including one that wrote only an excluded column.
_EXCLUDED_EVERYWHERE: frozenset[str] = frozenset({"updated_at"})


def digest(db_path: Path) -> str:
    """A hex digest of the collection's content in the SQLite file at `db_path`.

    Rows are read in primary-key order, so the digest does not depend on
    where SQLite happens to keep them on disk. Raises SQLAlchemy's
    `DBAPIError` if the file cannot be read — the caller decides what an
    unreadable database means for its gate.
    """
    engine = create_engine(f"sqlite:///file:{db_path}?mode=ro&uri=true")
    try:
        h = hashlib.sha256()
        with engine.connect() as conn:
            for table in Base.metadata.sorted_tables:
                if table.name in EXCLUDED_TABLES:
                    continue
                skip = EXCLUDED_COLUMNS.get(table.name, frozenset()) | _EXCLUDED_EVERYWHERE
                columns = [c for c in table.columns if c.name not in skip]
                if not columns:
                    continue
                h.update(f"\x00{table.name}:{','.join(c.name for c in columns)}\x00".encode())
                ordered = select(*columns).order_by(*table.primary_key.columns)
                for row in conn.execute(ordered):
                    h.update(repr(tuple(row)).encode())
                    h.update(b"\x1e")
        return h.hexdigest()[:32]
    finally:
        engine.dispose()
