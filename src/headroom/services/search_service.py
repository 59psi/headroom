from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.models.hat_color import HatColor
from headroom.models.room import Room
from headroom.services.hat_service import hat_loads
from headroom.services.color_extraction import (
    families_of_lab,
    is_same_color,
    lab_distance,
    lab_of,
)


def _in_room(room_id: int):
    """A hat is in a room two ways, and both count.

    Via its case, or directly since 2.33 (a shelf, a hook, a stand). One
    definition because the plain search and the color search both filter on
    it, and `Hat.room_id` is a Python `@property` that cannot appear in a
    `WHERE` clause — so each caller would otherwise write the disjunction out
    and one of them would eventually forget half of it.
    """
    return or_(
        Hat.case.has(Case.room_id == room_id),
        Hat.direct_room_id == room_id,
    )


def _color_rank_clause(scope: str):
    """The dominance-rank restriction for a color term, as WHERE args.

    Returns a tuple so the caller can splat it — `all` contributes nothing
    rather than a `True` literal SQLAlchemy would render into the SQL.

    An unknown scope falls back to `major` rather than raising: this is reached
    from a query string, and the safe reading of a typo is the default, not a
    500 and not a silently wider search.
    """
    if scope == "all":
        return ()
    if scope == "accent":
        return (HatColor.dominance_rank > MAJOR_COLOR_RANK,)
    return (HatColor.dominance_rank <= MAJOR_COLOR_RANK,)


#: Colors at this dominance rank or better are what the hat IS; anything
#: deeper is an accent — a logo, a piping, an underbrim.
#:
#: Searching "pink" used to return a black cap with a pink embroidered logo
#: alongside actual pink hats, because the clause matched ANY row in
#: `hat_colors`. Every melin hat is a dark crown with a bright mark on it, so
#: that made color terms close to useless: the accent colors are precisely
#: the ones that vary.
#:
#: Keyed on `dominance_rank`, not `tier`, for the same reason the color-
#: similarity ranking is: `tier` arrives from the client on the manual-edit
#: path and can disagree with the position the row is actually stored at.
MAJOR_COLOR_RANK = 2

#: Which swatches a color term is allowed to match.
#:
#: `accent` is not merely the complement of the default — it is its own useful
#: question. "Which of my hats has pink on it somewhere" is exactly how you
#: look for a collab mark or a contrast underbrim, and asking it against the
#: whole collection returns almost everything.
COLOR_SCOPES = ("major", "accent", "all")

#: How many results a search returns. A backstop, not a page: the UI has no
#: paging, so anything past this is simply unfindable.
SEARCH_LIMIT = 50



async def search_hats(
    db: AsyncSession,
    query: str,
    *,
    exact_colors: bool = False,
    room_id: int | None = None,
    public_fields_only: bool = False,
    color_scope: str = "major",
    limit: int | None = SEARCH_LIMIT,
) -> list[Hat]:
    """Multi-term AND search across hat fields and color names.

    Each term must match at least one field (style, condition, size,
    a color name/general_color, or room name).

    When exact_colors is False (default), color terms match against
    general_color — the curated palette name the hex was snapped to (e.g.
    "red", "dark gray"). When True, matches against the stored `color_name`,
    which is whatever the analyzer called it ("charcoal heather", "bone").
    """
    terms = query.strip().split()
    if not terms:
        return []

    stmt = select(Hat).options(
        *hat_loads(),
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
            # Major colors only unless asked otherwise — see
            # `MAJOR_COLOR_RANK`. A hat is not "pink" because its logo is.
            Hat.id.in_(
                select(HatColor.hat_id).where(
                    color_field.ilike(pattern), *_color_rank_clause(color_scope)
                )
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

    stmt = stmt.order_by(Hat.id)
    # `None` means uncapped. The guest view passes it: its response reports
    # `len()` as the match count, and a capped list makes that count a lie —
    # the mistake this codebase has made three times over (colorway catalog,
    # analysis `pending_count`, and the guest search itself, first at 50 and
    # then at 500). The guest's BROWSE path already returns the whole active
    # collection uncapped, so a search, which can only return a subset of it,
    # gains nothing from a ceiling the browse does not have.
    if limit is not None:
        stmt = stmt.limit(limit)
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
# The per-rank distance BUDGET lives in `_RANK_DISTANCE_BUDGET` just below
# (secondary within 18, deeper within 12); these penalties only ORDER what
# passes it. "Find the hat with the pink brim" still works, but it has to be
# that pink and it never outranks a hat that IS pink.
_RANK_PENALTY: dict[int, float] = {1: 0.0, 2: 8.0, 3: 14.0}
_DEEPER_RANK_PENALTY = 18.0

#: How far from the target a swatch at each rank may sit and still count.
#:
#: `None` for rank 1: a hat's MAIN color being the right color is the whole
#: question, and light blue sits ΔE 55.8 from navy while both are plainly
#: blue — so any number here would throw away true matches. Accents get a
#: budget because "the hat with the pink brim" has to actually be pink.
_RANK_DISTANCE_BUDGET: dict[int, float] = {1: float("inf"), 2: 18.0}
_DEEPER_RANK_BUDGET = 12.0

# THERE IS NO DISTANCE CUTOFF ANY MORE, and removing it is the fix.
#
# The history is four attempts at one number. Before 2.20 there was no ceiling
# at all, so a teal search returned thirty hats — six teal and twenty-four
# presented identically beside them. 2.20 set 30, 2.22 cut it to 22, 2.23
# relaxed it to 26. Every one of those was the same mistake, and the comment
# sitting here already said so: a distance threshold cannot answer "is this
# hat purple?", and tuning it will never make it.
#
# The measurement that ends the argument. Across the curated palette:
#
#     within-family distances    up to ΔE 55.8   (light blue → navy)
#     cross-family distances     down to ΔE 15.4 (black → navy)
#
# The ranges do not overlap, they INVERT. No threshold can keep light blue and
# navy together while separating black from navy, because the pair that must
# match is three and a half times further apart than the pair that must not.
# At 26 there were 51 cross-family pairs matching — black/navy, silver/beige,
# white/cream, charcoal/dark brown — which is why every search came back
# looking like the whole collection.
#
# Membership is now decided by `color_family`, on the curated names, where the
# question has an exact answer. Distance keeps the job it is genuinely good
# at: ORDERING hats that are already the right color, nearest first, with the
# rank penalty below still deciding that a hat which IS pink outranks one with
# a pink brim. `limit` bounds the list, as it always did.


@dataclass(frozen=True)
class ColorMatch:
    """One hat's best swatch against a search color."""

    hat: Hat
    hex_value: str  # the swatch that matched
    distance: float  # raw CIEDE2000 from the target to that swatch
    rank: int  # its dominance_rank — 1 is the hat's main color
    score: float  # distance + rank penalty; what the ordering uses


async def search_hats_by_color(
    db: AsyncSession,
    hex_value: str,
    *,
    room_id: int | None = None,
    limit: int = 30,
) -> list[ColorMatch]:
    """Rank active hats by perceptual closeness to `hex_value`, nearest first.

    A hat is scored on its best swatch, where "best" weighs perceptual
    distance against how much of the hat wears that color: a hat whose
    SECONDARY color matches still surfaces — that is the "find something
    light blue" job — but it ranks below a hat whose main color does, which
    is what min-across-swatches got wrong.

    Membership is decided by COLOR FAMILY, not by distance — a hat is
    returned when one of its swatches is the same color as the target, in
    the plain-speech sense the curated palette names. Distance cannot decide
    whether a gray hat is purple, and no threshold ever could: within-family
    distances reach ΔE 55.8 while cross-family ones start at 15.4, so the two
    ranges invert. Distance ranks what is already the right color.

    Hat counts are hundreds, not millions: loading candidates and ranking in
    Python beats teaching SQLite color science.
    """
    stmt = (
        select(Hat)
        .options(
            *hat_loads(),
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
    target_families = families_of_lab(target_lab)

    ranked: list[ColorMatch] = []
    for hat in result.scalars().all():
        best: ColorMatch | None = None
        for color in hat.colors or []:
            if not color.hex_value:
                continue
            swatch_lab = lab_of(color.hex_value)
            if swatch_lab is None:
                continue
            # MEMBERSHIP IS CATEGORICAL. A gray hat is not a dark purple and
            # a navy one is not black, at any distance — they are not near
            # each other by a lot or a little, they are different colors.
            #
            # Prefer the stored palette name, which is what the hat is
            # recorded as being; fall back to snapping the hex for swatches
            # that predate color normalization.
            if not is_same_color(
                target_lab, swatch_lab, color.general_color, target_families=target_families
            ):
                continue
            rank = color.dominance_rank
            # A per-rank DISTANCE BUDGET, stated directly rather than emerging
            # from a penalty meeting a global cutoff. Being the right color
            # family is enough for a hat's main color; an accent has to also
            # be a close match, or "show me the pink ones" fills up with hats
            # that merely have a pinkish logo. Same intent the rank penalty
            # had when there was a cutoff for it to work against — now that
            # membership is categorical, the budget has to say so itself.
            distance = lab_distance(target_lab, swatch_lab)
            if distance > _RANK_DISTANCE_BUDGET.get(rank, _DEEPER_RANK_BUDGET):
                continue
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
        if best is not None:
            ranked.append(best)

    ranked.sort(key=lambda match: match.score)
    return ranked[:limit]
