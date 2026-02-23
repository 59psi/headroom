from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.hat import Hat
from headroom.models.hat_color import HatColor


async def search_hats(db: AsyncSession, query: str) -> list[Hat]:
    """Multi-term AND search across hat fields and color names.

    Each term must match at least one field (style, condition, size,
    or a color name).
    """
    terms = query.strip().split()
    if not terms:
        return []

    stmt = select(Hat).options(selectinload(Hat.case), selectinload(Hat.colors))

    for term in terms:
        pattern = f"%{term}%"
        # Each term must match something
        term_filter = or_(
            Hat.style.ilike(pattern),
            Hat.condition.ilike(pattern),
            Hat.size.ilike(pattern),
            Hat.id.in_(
                select(HatColor.hat_id).where(HatColor.color_name.ilike(pattern))
            ),
        )
        stmt = stmt.where(term_filter)

    stmt = stmt.order_by(Hat.id).limit(50)
    result = await db.execute(stmt)
    return list(result.scalars().all())
