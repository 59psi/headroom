from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.models.hat_color import HatColor
from headroom.models.room import Room
from headroom.services.color_extraction import lab_distance, lab_of


async def search_hats(
    db: AsyncSession,
    query: str,
    *,
    exact_colors: bool = False,
    room_id: int | None = None,
) -> list[Hat]:
    """Multi-term AND search across hat fields and color names.

    Each term must match at least one field (style, condition, size,
    a color name/general_color, or room name).

    When exact_colors is False (default), color terms match against
    general_color (e.g. "red", "dark gray"). When True, matches against
    the specific CSS3 color_name (e.g. "darkslategray", "silver").
    """
    terms = query.strip().split()
    if not terms:
        return []

    stmt = select(Hat).options(
        selectinload(Hat.case).selectinload(Case.room),
        selectinload(Hat.colors),
    )

    # Disposed hats can't be "found" — they're not in any case anymore.
    stmt = stmt.where(Hat.disposed_at.is_(None))

    if room_id is not None:
        stmt = stmt.where(Hat.case.has(Case.room_id == room_id))

    color_field = HatColor.color_name if exact_colors else HatColor.general_color

    for term in terms:
        pattern = f"%{term}%"
        # Each term must match something
        clauses = [
            Hat.style.ilike(pattern),
            Hat.condition.ilike(pattern),
            Hat.size.ilike(pattern),
            Hat.brand.ilike(pattern),
            Hat.model_name.ilike(pattern),
            Hat.artist_series.ilike(pattern),
            Hat.id.in_(
                select(HatColor.hat_id).where(color_field.ilike(pattern))
            ),
            Hat.case.has(Case.room.has(Room.name.ilike(pattern))),
        ]
        # HYDRO / HYDROLite are boolean columns, not text, so no `ilike` above
        # can ever match them. They used to be values of `style`, and USAGE
        # still promised "`hydro` finds every Hydro" — moving them to flags in
        # 2.6.0 quietly broke that. Matched on the term itself so the promise
        # holds again. "hydro" is a prefix of "hydrolite", so check the longer
        # word first or every HYDROLite search also drags in every HYDRO.
        low = term.lower()
        if "hydrolite" in low:
            clauses.append(Hat.hydrolite.is_(True))
        elif "hydro" in low:
            clauses.append(Hat.hydro.is_(True))
        stmt = stmt.where(or_(*clauses))

    stmt = stmt.order_by(Hat.id).limit(50)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def search_hats_by_color(
    db: AsyncSession,
    hex_value: str,
    *,
    room_id: int | None = None,
    limit: int = 30,
) -> list[tuple[Hat, str, float]]:
    """Rank active hats by perceptual closeness to `hex_value`.

    Distance is the minimum ΔE over a hat's stored swatches, so a hat whose
    *secondary* color matches still surfaces — exactly the "find something
    light blue" job. Returns (hat, matched_hex, distance), nearest first.

    Hat counts are hundreds, not millions: loading candidates and ranking in
    Python beats teaching SQLite color science.
    """
    stmt = (
        select(Hat)
        .options(
            selectinload(Hat.case).selectinload(Case.room),
            selectinload(Hat.colors),
        )
        .where(Hat.disposed_at.is_(None))
    )
    if room_id is not None:
        stmt = stmt.where(Hat.case.has(Case.room_id == room_id))
    result = await db.execute(stmt)

    # Convert the target once, not once per stored swatch: this loop runs
    # (hats x swatches) times and `_srgb_to_lab` is three `** 2.4` powers.
    target_lab = lab_of(hex_value)
    if target_lab is None:
        return []

    ranked: list[tuple[Hat, str, float]] = []
    for hat in result.scalars().all():
        best: tuple[str, float] | None = None
        for color in hat.colors or []:
            if not color.hex_value:
                continue
            swatch_lab = lab_of(color.hex_value)
            if swatch_lab is None:
                continue
            d = lab_distance(target_lab, swatch_lab)
            if best is None or d < best[1]:
                best = (color.hex_value, d)
        if best is not None:
            ranked.append((hat, best[0], round(best[1], 2)))

    ranked.sort(key=lambda item: item[2])
    return ranked[:limit]
