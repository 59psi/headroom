"""Free-text fields that should not accumulate spellings of the same thing.

`construction` and `artist_series` are deliberately free text — melin ships
specialty fabrics and named collections whenever it likes, and a closed list
makes each one unrecordable until someone ships a migration. The cost of that
freedom is drift: type "Neon" today, "NEON" next month, "neon" from the phone,
and one collection becomes three, none of which find each other in search.

Two layers stop it:

1. **Suggestions.** `GET /api/meta/*` serves the values already in use, so the
   common path is tapping the existing one rather than retyping it.
2. **Canonicalization, here.** Suggestions can be typed past, so a value that
   case-insensitively matches something already recorded is stored with the
   EXISTING spelling. That is what makes the guarantee hold rather than merely
   making duplicates less likely.

Two spellings are the same when `naming.name_key` says so — the ONE "same
name" rule, shared with the purchase matcher and duplicate detection. It folds
case, width, whitespace, punctuation AND accents, so "Piña", "Pina" and "PINA"
are one collection, as are "A-Game" and "A Game". Accents were initially left
alone on the theory that two names differing only by a diacritic might
genuinely be different — in this collection they aren't, they are the same
drop typed with and without a long-press on a phone keyboard, and three
entries that never find each other in search is the concrete harm. This
module used to carry its own fold, which the matcher did not share: a
colorway canonicalized here as one value was two products there.

When variants disagree, the ACCENTED spelling wins (see `_preferred`): an
accent is a deliberate act, while dropping one is what happens when you're
typing quickly, so the accented form is the better guess at the real name.
"""

from __future__ import annotations

import unicodedata

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute

from headroom.services.naming import name_key


def _key(value: str) -> str:
    """`name_key`, or the collapsed value itself when it has no letters or
    digits — so two different punctuation-only values stay two, rather than
    both keying to "" and merging."""
    return name_key(value) or " ".join(value.split())


def _accent_count(value: str) -> int:
    """How many combining marks a spelling carries."""
    return sum(1 for c in unicodedata.normalize("NFKD", value) if unicodedata.combining(c))


def _preferred(variants: list[str], known: tuple[str, ...] = ()) -> str:
    """Pick the spelling to keep from a group that folds to the same key.

    One rule, used by both write-time canonicalization and the one-time merge,
    so a value cannot land differently depending on which path reached it.

    In order: a curated spelling if one matches; then the most accents, because
    adding one is deliberate and dropping one is a slip; then the most common,
    so a single early typo doesn't rename what everything else uses; then
    alphabetical, purely so the result never depends on row order.
    """
    key = _key(variants[0])
    for candidate in known:
        if _key(candidate) == key:
            return candidate

    counts: dict[str, int] = {}
    for v in variants:
        counts[v] = counts.get(v, 0) + 1
    # The last resort is spelled out rather than left to plain string order:
    # ASCII sorts `NEON` before `Neon`, so a dead heat went to the shouting
    # one. Fewest capitals after the first letter wins the heat, then the
    # case-insensitive order keeps the result independent of row order.
    return sorted(
        counts,
        key=lambda v: (-_accent_count(v), -counts[v], _shouting(v), v.casefold(), v),
    )[0]


def _shouting(value: str) -> int:
    """Words written in ALL CAPS — `NEON` 1, `Neon` 0, `Skye Walker` 0.

    Whole words, not capital letters: Title Case is how a collection is
    named and must not lose to the lowercase spelling a phone keyboard
    produces.
    """
    return sum(1 for word in value.split() if len(word) > 1 and word.isupper())


async def distinct_values(
    db: AsyncSession,
    column: InstrumentedAttribute,
    limit: int = 500,
    known: tuple[str, ...] = (),
) -> list[str]:
    """Every value in use for `column`, one spelling per name, alphabetical.

    The spelling offered is `_preferred`'s — the one a write would store, with
    the same curated `known` list a write would be given. This used to keep
    whichever variant sorted first, so with `NEON` on one hat and `Neon` on
    three the picker suggested `NEON` while typing either stored `Neon`; and
    `_known_series` hands this list to Claude as the spelling to use EXACTLY,
    so the analysis path learned the minority spelling too.

    Counted per spelling, because `_preferred` breaks ties by how common a
    spelling is. Bounded because this backs a picker, not a report.
    """
    rows = (
        await db.execute(
            select(column, func.count())
            .where(column.is_not(None))
            .group_by(column)
        )
    ).all()

    groups: dict[str, list[str]] = {}
    for raw, count in rows:
        if not raw or not raw.strip():
            continue
        cleaned = " ".join(raw.split())
        groups.setdefault(_key(cleaned), []).extend([cleaned] * count)

    chosen = sorted(
        (_preferred(variants, known) for variants in groups.values()), key=str.casefold
    )
    return chosen[:limit]


async def canonicalize(
    db: AsyncSession,
    column: InstrumentedAttribute,
    value: str | None,
    known: tuple[str, ...] = (),
) -> str | None:
    """Return the spelling already on record for `value`, or `value` as typed.

    Whitespace is always normalized — trailing spaces are never meaningful and
    are invisible in a picker, so " Neon" and "Neon " would otherwise be two
    more variants nobody could tell apart.

    `known` is a curated vocabulary (e.g. `KNOWN_CONSTRUCTIONS`) and is checked
    FIRST, because it is authoritative even before any hat uses it: typing
    "hydrolite" into an empty database would otherwise store that spelling and
    leave the field permanently at odds with the list offering "HYDROLite".

    Matching happens in Python, not SQL. It used to be a
    `WHERE lower(col) = lower(?)`, which cannot fold accents — SQLite's
    `lower()` is ASCII-only, so "Piña" and "PIÑA" don't even match each other
    there, let alone "Pina". The candidate set is the DISTINCT values of one
    column on a personal collection, so reading it per write is a few dozen
    short strings.
    """
    if value is None:
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        return None

    key = _key(cleaned)
    for candidate in known:
        if _key(candidate) == key:
            return candidate

    # ALL rows, not `DISTINCT`: `_preferred` decides ties by how common a
    # spelling is, and a distinct list hands it every spelling with a count
    # of one. With three hats recorded as `Neon` and one as `NEON`, a typed
    # `neon` was stored as `NEON` — the tiebreak fell through to ASCII order,
    # which ranks capitals first. The merge path already read every row; the
    # write path was the one deciding on a fiction.
    # `no_autoflush`: the analysis path assigns the value to the hat BEFORE
    # canonicalizing it, and an autoflush would push that dirty spelling into
    # the rows being counted — the value under judgment voting for itself.
    with db.no_autoflush:
        rows = (
            await db.execute(select(column).where(column.is_not(None)))
        ).scalars().all()
    matches = [" ".join(r.split()) for r in rows if r and r.strip() and _key(r) == key]
    if not matches:
        return cleaned

    on_record = _preferred(matches, known)
    # What's on record wins ties — "snap to the existing spelling" is the whole
    # point, and letting the typed form compete on equal terms would make
    # "NEON" rename a collection recorded as "Neon" just by being typed once.
    # It only loses when the typed value is strictly better informed, which
    # here means it carries accents the stored one dropped. The merge then
    # pulls the older rows across.
    if _accent_count(cleaned) > _accent_count(on_record):
        return cleaned
    return on_record


async def merge_case_variants(
    db: AsyncSession, column: InstrumentedAttribute, known: tuple[str, ...] = ()
) -> int:
    """Collapse existing spelling variants (`name_key`) onto one spelling.

    Returns the number of rows changed.

    Canonicalization only applies to writes, so anything already recorded keeps
    whatever was typed at the time — this is the one-time repair for values
    that entered before it, or through an import. `_preferred` decides which
    spelling wins, so the merge and the write path cannot disagree.

    Rows are matched by their exact stored value rather than by a SQL
    expression, because the key folds accents and punctuation and SQLite's
    `lower()` is ASCII-only — a `WHERE lower(col) = key` would silently skip
    every accented row, which is precisely the group this exists to merge.

    Idempotent — running it again after it has converged changes nothing.
    """
    rows = (
        await db.execute(select(column).where(column.is_not(None)))
    ).scalars().all()

    groups: dict[str, list[str]] = {}
    for raw in rows:
        if not raw or not raw.strip():
            continue
        groups.setdefault(_key(raw), []).append(raw)

    changed = 0
    for variants in groups.values():
        # Compare on the cleaned form, but rewrite by the RAW stored value:
        # " neon " and "neon" are the same variant to us and different strings
        # to the database.
        winner = _preferred([" ".join(v.split()) for v in variants], known)
        stale = {v for v in variants if v != winner}
        if not stale:
            continue
        result = await db.execute(
            column.parent.class_.__table__.update()
            .where(column.in_(stale))
            .values({column.key: winner})
        )
        changed += result.rowcount or 0

    if changed:
        await db.commit()
    return changed
