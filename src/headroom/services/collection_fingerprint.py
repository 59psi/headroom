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
tables and columns that are the app's own bookkeeping OR a scraped market
figure. A checkpoint moves no rows; a login writes only excluded tables; and —
the change in 2.86.0 — a re-pricing sweep now moves nothing the gate counts,
whether or not a median moved.

Scraped resale/eBay prices are DERIVED, not owner data: they are regenerated
from a live marketplace on every sweep and drift night to night on their own,
so treating a moved median as "the collection changed" made the nightly sweep
(on by default) reopen the gate almost every night — a KEEP=5 window covering
five days of price drift instead of five real edits to the shelf, which is the
exact erosion this gate exists to stop. A restore does not need last night's
median; it needs your hats, cases, wears, purchases and the prices you entered
by hand. So the whole scraped-price surface is excluded (see EXCLUDED_COLUMNS),
and only owner-driven content opens the gate. (Trade-off: a *manual* resale
price, which shares the `resale_price` column, no longer opens the gate on its
own either — it rides into the next backup a real edit triggers. Prices are
reproducible from the market; the rest is not.)

Reading a few thousand rows is milliseconds, cheap beside the tarball it
decides about.

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

#: Columns rewritten on rows whose content did not change, OR that hold a
#: scraped market figure that drifts on its own. Everything else in a table is
#: owner-driven content.
EXCLUDED_COLUMNS: dict[str, frozenset[str]] = {
    # The whole scraped-price surface, melin and eBay alike. These are DERIVED
    # from a live marketplace on every re-pricing sweep (on by default, nightly)
    # and move night to night with no owner action, so counting them as "the
    # collection changed" made the gate reopen almost every night — the days-
    # not-changes window this gate exists to prevent. A restore reproduces them
    # from the market; it does not need last night's median.
    #
    #   resale_checked_at / ebay_checked_at  — "when the marketplace was last asked"
    #   resale_price_source                  — the label, e.g. "median of 8 live listings"
    #                                          (its count churns as listings come and go)
    #   resale_price / resale_price_scope    — the melin median and whether it was
    #                                          matched by model or by category
    #   ebay_avg_price / ebay_median_price / ebay_listing_count — the eBay comps
    #
    # A MANUAL resale price lives in `resale_price` too, so excluding the column
    # means a hand-entered price no longer opens the gate on its own — it is
    # captured by the next backup a real edit triggers. Owner data that is not a
    # scraped price (notes, condition, disposition, cost basis, wears, slots…)
    # all stays IN and still opens the gate. See the module docstring.
    "hats": frozenset({
        "resale_checked_at",
        "ebay_checked_at",
        "resale_price_source",
        "resale_price",
        "resale_price_scope",
        "ebay_avg_price",
        "ebay_median_price",
        "ebay_listing_count",
    }),
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
