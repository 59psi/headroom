"""Free-text fields that should not accumulate spellings of the same thing.

`construction` and `artist_series` are deliberately free text — melin ships
specialty fabrics and named collections whenever it likes, and a closed list
makes each one unrecordable until someone ships a migration. The cost of that
freedom is drift: type "Neon" today, "NEON" next month, "neon" from the phone,
and one collection becomes three, none of which find each other in search.

Two layers stop it:

1. **Suggestions.** `GET /api/meta/*` serves the values already in use, so the
   common path is tapping the existing one rather than retyping it.
2. **Canonicalisation, here.** Suggestions can be typed past, so a value that
   case-insensitively matches something already recorded is stored with the
   EXISTING spelling. That is what makes the guarantee hold rather than merely
   making duplicates less likely.

Deliberately only case/whitespace folding. "Piña" and "Pina" stay distinct:
collapsing accents would be guessing at intent, and merging two collections
that are genuinely different is worse than keeping two spellings of one.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute


def _fold(value: str) -> str:
    return " ".join(value.split()).casefold()


async def distinct_values(
    db: AsyncSession, column: InstrumentedAttribute, limit: int = 500
) -> list[str]:
    """Every non-empty value in use for `column`, alphabetical, de-duplicated.

    Case-insensitive de-dupe keeping the FIRST spelling seen in alphabetical
    order — deterministic, so the suggestion list doesn't reshuffle between
    requests. Bounded because this backs a picker, not a report.
    """
    rows = (
        await db.execute(
            select(column).where(column.is_not(None)).distinct().limit(limit)
        )
    ).scalars().all()

    seen: dict[str, str] = {}
    for raw in sorted((r.strip() for r in rows if r and r.strip()), key=str.casefold):
        seen.setdefault(_fold(raw), raw)
    return list(seen.values())


async def canonicalize(
    db: AsyncSession,
    column: InstrumentedAttribute,
    value: str | None,
    known: tuple[str, ...] = (),
) -> str | None:
    """Return the spelling already on record for `value`, or `value` as typed.

    Whitespace is always normalised — trailing spaces are never meaningful and
    are invisible in a picker, so " Neon" and "Neon " would otherwise be two
    more variants nobody could tell apart.

    `known` is a curated vocabulary (e.g. `KNOWN_CONSTRUCTIONS`) and is checked
    FIRST, because it is authoritative even before any hat uses it: typing
    "hydrolite" into an empty database would otherwise store that spelling and
    leave the field permanently at odds with the list offering "HYDROLite".
    """
    if value is None:
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        return None

    for candidate in known:
        if candidate.casefold() == cleaned.casefold():
            return candidate

    existing = (
        await db.execute(
            select(column)
            .where(func.lower(column) == cleaned.lower())
            .limit(1)
        )
    ).scalar_one_or_none()
    return existing or cleaned


async def merge_case_variants(
    db: AsyncSession, column: InstrumentedAttribute, known: tuple[str, ...] = ()
) -> int:
    """Collapse existing case/whitespace variants onto one spelling. Returns rows changed.

    Canonicalisation only applies to writes, so anything already recorded keeps
    whatever was typed at the time — this is the one-time repair for values
    that entered before it, or through an import.

    Which spelling wins: a curated one if it matches, else the most COMMON
    variant, with alphabetical order breaking ties so the outcome does not
    depend on row order. Most-common rather than first-seen because a single
    early typo should not rename the collection everything else uses.

    Idempotent — running it again after it has converged changes nothing.
    """
    rows = (
        await db.execute(select(column).where(column.is_not(None)))
    ).scalars().all()

    groups: dict[str, list[str]] = {}
    for raw in rows:
        if not raw or not raw.strip():
            continue
        cleaned = " ".join(raw.split())
        groups.setdefault(_fold(cleaned), []).append(cleaned)

    curated = {k.casefold(): k for k in known}
    changed = 0
    for key, variants in groups.items():
        winner = curated.get(key)
        if winner is None:
            counts: dict[str, int] = {}
            for v in variants:
                counts[v] = counts.get(v, 0) + 1
            winner = sorted(counts, key=lambda v: (-counts[v], v))[0]

        result = await db.execute(
            column.parent.class_.__table__.update()
            .where(func.lower(func.trim(column)) == key)
            .where(column != winner)
            .values({column.key: winner})
        )
        changed += result.rowcount or 0

    if changed:
        await db.commit()
    return changed
