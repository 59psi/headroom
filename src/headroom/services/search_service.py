from dataclasses import dataclass

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
            # Free-form since 2.11, so "canvas" finds a Waxed Canvas hat. The
            # flag clauses below stay because they are not redundant with this:
            # `hydro` must keep finding a hat recorded as "A-Game Hydro", and
            # `hydrolite` must NOT drag in every HYDRO.
            Hat.construction.ilike(pattern),
            Hat.id.in_(
                select(HatColor.hat_id).where(color_field.ilike(pattern))
            ),
            Hat.case.has(Case.room.has(Room.name.ilike(pattern))),
        ]
        # HYDRO / HYDROLite also have boolean columns, derived from the text
        # above. They used to be values of `style`, and USAGE still promised
        # "`hydro` finds every Hydro" — moving them to flags in 2.6.0 quietly
        # broke that. Matched on the term itself so the promise holds again.
        # "hydro" is a prefix of "hydrolite", so check the longer word first or
        # every HYDROLite search also drags in every HYDRO.
        low = term.lower()
        if "hydrolite" in low:
            clauses.append(Hat.hydrolite.is_(True))
        elif "hydro" in low:
            clauses.append(Hat.hydro.is_(True))
        stmt = stmt.where(or_(*clauses))

    stmt = stmt.order_by(Hat.id).limit(50)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# How much worse a match counts for being on a less dominant swatch.
#
# Added in ΔE units and keyed on `dominance_rank`, not `tier`: rank is
# assigned positionally by every writer (`enumerate(..., start=1)` in the
# analysis pipeline, the fallback path and `PUT /api/hats/{id}/colors`),
# whereas `tier` arrives from the client on the manual-edit path and can
# disagree with the position it is stored at.
#
# Without this, a hat matched on the MINIMUM distance across all its swatches,
# so every swatch counted the same and a hat with four of them got four
# chances to match anything. On this collection that is not a corner case: a
# melin hat is a dark neutral crown with a bright logo, so searching pink
# ranked a green hat with a pink logo EQUAL FIRST with a hat that is actually
# pink — both scored 0.0, and nothing in the result list explained why.
#
# Additive rather than multiplicative, because a multiplier leaves an exact
# accent match at 0.0 and changes nothing about the tie it needs to break.
# The penalty doubles as a per-rank distance budget once the cutoff is
# applied: a secondary must land within 14 of the target to appear at all, an
# accent within 8. "Find the hat with the pink brim" still works, but it has
# to be that pink and it never outranks a hat that IS pink.
_RANK_PENALTY: dict[int, float] = {1: 0.0, 2: 8.0, 3: 14.0}
_DEEPER_RANK_PENALTY = 18.0

# How bad a match score may be and still be called a match.
#
# There was no ceiling at all before 2.20, only `limit`: every active hat was
# ranked and the nearest N returned however far away they were, so searching a
# specific teal in a collection of a hundred returned thirty hats — six teal,
# and twenty-four presented identically beside them.
#
# 2.20 set it to 30, calibrated against the curated palette in
# `color_extraction` on the reasoning that its 26 entries are deliberately
# distinct, so the gap between any two is a lower bound on "different enough
# to have its own name". That was the wrong distribution to calibrate on. The
# palette is spread evenly around the wheel; a hat collection is not. These
# hats are overwhelmingly black, charcoal, navy and grey, and CIEDE2000 places
# a low-chroma neutral moderately near EVERYTHING — at 30, grey is a "match"
# for 17 of the other 25 palette colours, red, orange, purple and pink
# included. Every hat owns a grey swatch, so every search returned every hat,
# all bunched at a distance that made them look equally relevant.
#
# 22 is calibrated on the neutrals instead, where the problem lives:
#
#                     within 30      within 22
#     gray               17            4  (silver, tan, teal, olive)
#     charcoal           11            5
#     pink                4            1
#     red                 6            1
#
# Saturated targets barely notice the change — they were never the complaint —
# while the neutral blowout that made the feature useless is gone. Distinct
# shades of one colour still match each other comfortably: a real grey crown
# (#6b7078) is 8.0 from the grey chip, well inside.
MAX_MATCH_SCORE = 22.0


@dataclass(frozen=True)
class ColorMatch:
    """One hat's best swatch against a search colour."""

    hat: Hat
    hex_value: str  # the swatch that matched
    distance: float  # raw CIEDE2000 from the target to that swatch
    rank: int  # its dominance_rank — 1 is the hat's main colour
    score: float  # distance + rank penalty; what the ordering uses


async def search_hats_by_color(
    db: AsyncSession,
    hex_value: str,
    *,
    room_id: int | None = None,
    limit: int = 30,
    max_score: float = MAX_MATCH_SCORE,
) -> list[ColorMatch]:
    """Rank active hats by perceptual closeness to `hex_value`, nearest first.

    A hat is scored on its best swatch, where "best" weighs perceptual
    distance against how much of the hat wears that colour: a hat whose
    SECONDARY colour matches still surfaces — that is the "find something
    light blue" job — but it ranks below a hat whose main colour does, which
    is what min-across-swatches got wrong. Anything scoring beyond `max_score`
    is dropped rather than padding the list out to `limit`.

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

    ranked: list[ColorMatch] = []
    for hat in result.scalars().all():
        best: ColorMatch | None = None
        for color in hat.colors or []:
            if not color.hex_value:
                continue
            swatch_lab = lab_of(color.hex_value)
            if swatch_lab is None:
                continue
            rank = color.dominance_rank
            distance = lab_distance(target_lab, swatch_lab)
            score = distance + _RANK_PENALTY.get(rank, _DEEPER_RANK_PENALTY)
            if best is None or score < best.score:
                best = ColorMatch(
                    hat=hat,
                    hex_value=color.hex_value,
                    distance=round(distance, 2),
                    rank=rank,
                    score=score,
                )
        # Thresholded on the unrounded score: a match at 22.004 is not
        # meaningfully different from one at 21.996, but rounding first would
        # let the displayed number and the cutoff disagree at the boundary.
        if best is not None and best.score <= max_score:
            ranked.append(best)

    ranked.sort(key=lambda match: match.score)
    return ranked[:limit]
