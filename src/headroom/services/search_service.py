from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.models.hat_color import HatColor
from headroom.models.room import Room
from headroom.services.color_extraction import color_distance


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
        term_filter = or_(
            Hat.style.ilike(pattern),
            Hat.condition.ilike(pattern),
            Hat.size.ilike(pattern),
            Hat.brand.ilike(pattern),
            Hat.model_name.ilike(pattern),
            Hat.id.in_(
                select(HatColor.hat_id).where(color_field.ilike(pattern))
            ),
            Hat.case.has(Case.room.has(Room.name.ilike(pattern))),
        )
        stmt = stmt.where(term_filter)

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

    ranked: list[tuple[Hat, str, float]] = []
    for hat in result.scalars().all():
        best: tuple[str, float] | None = None
        for color in hat.colors or []:
            if not color.hex_value:
                continue
            d = color_distance(hex_value, color.hex_value)
            if d is not None and (best is None or d < best[1]):
                best = (color.hex_value, d)
        if best is not None:
            ranked.append((hat, best[0], round(best[1], 2)))

    ranked.sort(key=lambda item: item[2])
    return ranked[:limit]
