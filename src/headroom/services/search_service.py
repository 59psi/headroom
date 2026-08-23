from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.models.hat_color import HatColor
from headroom.models.room import Room
from headroom.services.color_extraction import (
    is_neutral_mismatch,
    lab_distance,
    lab_of,
)


def _in_room(room_id: int):
    """A hat is in a room two ways, and both count.

    Via its case, or directly since 2.33 (a shelf, a hook, a stand). One
    definition because the plain search and the colour search both filter on
    it, and `Hat.room_id` is a Python `@property` that cannot appear in a
    `WHERE` clause — so each caller would otherwise write the disjunction out
    and one of them would eventually forget half of it.
    """
    return or_(
        Hat.case.has(Case.room_id == room_id),
        Hat.direct_room_id == room_id,
    )


#: How many results a search returns. A backstop, not a page: the UI has no
#: paging, so anything past this is simply unfindable.
SEARCH_LIMIT = 50

#: The limit used for guest search. Higher because the guest view has no
#: paging either AND reports the result count as the number of matches — a
#: truncated list would make that count a lie, which is the `len()`-of-a-capped
#: -list mistake this codebase has now made twice.
GUEST_SEARCH_LIMIT = 500


async def search_hats(
    db: AsyncSession,
    query: str,
    *,
    exact_colors: bool = False,
    room_id: int | None = None,
    public_fields_only: bool = False,
    limit: int = SEARCH_LIMIT,
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
        selectinload(Hat.direct_room),
        selectinload(Hat.colors),
    )

    # Disposed hats can't be "found" — they're not in any case anymore.
    stmt = stmt.where(Hat.disposed_at.is_(None))

    if room_id is not None:
        # A hat is in a room via its case OR directly (2.33). Filtering only
        # through the case excluded exactly the hats room-storage adds — and
        # silently, because the Hats page filters `room_id` client-side and so
        # kept showing them, leaving the two room filters disagreeing.
        stmt = stmt.where(_in_room(room_id))

    color_field = HatColor.color_name if exact_colors else HatColor.general_color

    for term in terms:
        pattern = f"%{term}%"
        # Each term must match something
        # Fields an outside viewer can already SEE — the ones `SharedHat`
        # carries. Safe to match on, because a hit reveals nothing the results
        # don't already show.
        clauses = [
            Hat.style.ilike(pattern),
            Hat.brand.ilike(pattern),
            Hat.model_name.ilike(pattern),
            Hat.id.in_(
                select(HatColor.hat_id).where(color_field.ilike(pattern))
            ),
            # Same reasoning as `room_id` above: both ways of being in a room.
            or_(
                Hat.case.has(Case.room.has(Room.name.ilike(pattern))),
                Hat.direct_room.has(Room.name.ilike(pattern)),
            ),
        ]
        if not public_fields_only:
            # Matching on a field the caller cannot see turns search into an
            # oracle for it: `?q=worn` returns exactly the worn hats, so a
            # guest could read every hat's condition by probing even though
            # `SharedHat` withholds it. Same for size, collection and
            # construction — and for the hydro/hydrolite flags below, which
            # are derived from construction.
            clauses += [
                Hat.condition.ilike(pattern),
                Hat.size.ilike(pattern),
                Hat.artist_series.ilike(pattern),
                # Free-form since 2.11, so "canvas" finds a Waxed Canvas hat.
                # The flag clauses below stay because they are not redundant
                # with this: `hydro` must keep finding a hat recorded as
                # "A-Game Hydro", and `hydrolite` must NOT drag in every HYDRO.
                Hat.construction.ilike(pattern),
            ]
            # HYDRO / HYDROLite also have boolean columns, derived from the
            # text above. They used to be values of `style`, and USAGE still
            # promised "`hydro` finds every Hydro" — moving them to flags in
            # 2.6.0 quietly broke that. Matched on the term itself so the
            # promise holds again. "hydro" is a prefix of "hydrolite", so check
            # the longer word first or every HYDROLite search also drags in
            # every HYDRO.
            #
            # Inside the same guard as `construction`: these are DERIVED from
            # it, so leaving them out here would close the front door and leave
            # the window open.
            low = term.lower()
            if "hydrolite" in low:
                clauses.append(Hat.hydrolite.is_(True))
            elif "hydro" in low:
                clauses.append(Hat.hydro.is_(True))
        stmt = stmt.where(or_(*clauses))

    stmt = stmt.order_by(Hat.id).limit(limit)
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
# This number was then tuned twice, downward, chasing a problem it could never
# have fixed. 2.20 set it to 30 against the curated palette; 2.22 cut it to 22
# against the neutrals. Both were the same mistake — trying to separate "grey"
# from "purple" with a distance threshold, when CIEDE2000 places a mid grey
# ~17 from a saturated purple and two genuinely different purples ~33 apart.
# No single cutoff exists that admits the second and rejects the first. That
# is now `is_neutral_mismatch`'s job, and it does it on the right axis.
#
# With the guard carrying that load the cutoff goes back to being about what
# it should always have measured — is this the same colour — and can relax to
# 26, which is where the palette says two named colours stop being versions of
# each other. Against 17 same-family pairs that must match and 12 cross-family
# pairs that must not:
#
#     cutoff   same-family kept   cross-family leaked
#       22          15/17             gold/lime, brown/olive
#       26          17/17             gold/lime, brown/olive     <- here
#       28          17/17             + navy/maroon
#
# 26 is the first value that keeps every same-family pair (navy/blue at 23.3
# and charcoal/gray at 25.3 were both casualties of 22). The two survivors are
# arguable rather than wrong — gold and lime are both yellows, brown and olive
# both dark earth tones. 28 admits navy/maroon, which is not arguable.
MAX_MATCH_SCORE = 26.0


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

    Swatches failing `is_neutral_mismatch` are not scored at all. Distance
    cannot decide whether a grey hat is purple, so nothing here tries: the
    hue question is answered first, and only then does distance rank what is
    left.

    Hat counts are hundreds, not millions: loading candidates and ranking in
    Python beats teaching SQLite color science.
    """
    stmt = (
        select(Hat)
        .options(
            selectinload(Hat.case).selectinload(Case.room),
            selectinload(Hat.direct_room),
            selectinload(Hat.colors),
        )
        .where(Hat.disposed_at.is_(None))
    )
    if room_id is not None:
        stmt = stmt.where(_in_room(room_id))
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
            # A grey hat is not a dark purple, at any distance. Checked
            # before scoring rather than folded into it, because there is no
            # penalty large enough to be principled here — the two colours
            # are not near each other by a lot or a little, they are simply
            # not the same kind of thing.
            if is_neutral_mismatch(target_lab, swatch_lab):
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
