"""What a case can still accept.

One definition of the rule, used by the validator that ENFORCES it on write and
by the read model that SHOWS it in the picker. With 40-60 cases the picker is
the only practical way to choose one, so a picker whose idea of "full" differs
from the server's produces a 409 on save with no warning — and the rule is
subtle enough (type exclusivity, a per-case override, disposed hats freeing
their slot) that two implementations would drift.
"""

from __future__ import annotations

from dataclasses import dataclass

# Nominal capacity when a case carries no explicit `capacity` — what "full"
# means. The physical article is a three-hat case; melin's own order lines
# call it a "3 Hat Travel Case". Beanies have no brim and squash flat, so far
# more fit in the same shell — eight, measured by the owner packing them, not
# derived from the three-hat figure.
MAX_REGULAR = 3
MAX_BEANIE = 8

# How far past nominal a DEFAULT case may be crammed. A fourth hat does go in,
# it just isn't how the case is meant to be loaded — so it's allowed on write
# and reported as *overfull* rather than silently accepted as normal.
#
# Deliberately not applied to a per-case `capacity` override. That field exists
# for "a Melin case you don't want to cram" (docs/USAGE.md §2), so a stated
# number is the number: quietly allowing one more would defeat the only reason
# to set it. Unset means "a standard case, with the usual latitude"; set means
# "I am telling you the limit".
OVERFILL_ALLOWANCE = 1

# Beanies get NO allowance. The regular allowance exists because 3 is melin's
# *name* for the case — a "3 Hat Travel Case" — and a fourth demonstrably fits,
# so the number to be lenient about was never a measurement. 8 is the opposite:
# it is what the owner fits in one, counted by packing it. Adding slack on top
# of a measured maximum asserts a ninth fits, which nobody has claimed.
BEANIE_OVERFILL_ALLOWANCE = 0


@dataclass(frozen=True)
class Acceptance:
    """Whether a case can take one more hat of each kind, and how many more."""

    accepts_regular: bool
    accepts_beanie: bool
    #: Slots left before the case is FULL. Zero once at nominal, even though
    #: one more may still be crammed in — "3 of 3" should read as full.
    free_regular: int
    free_beanie: int
    #: Nominal capacity: the number at which the case is full.
    max_regular: int
    max_beanie: int
    #: Already past nominal. Not an error, but the UI says so.
    overfull_regular: bool
    overfull_beanie: bool
    #: The hard ceiling a write is refused above (nominal + allowance).
    limit_regular: int
    limit_beanie: int


def evaluate(
    *, capacity: int | None, beanie_count: int, regular_count: int
) -> Acceptance:
    """Compute acceptance from a case's ACTIVE hat counts.

    Counts must exclude disposed hats — a disposed hat stays in the database
    but frees its slot, so counting it would show a case as fuller than the
    validator considers it.

    `capacity is not None`, not truthiness: a per-case capacity of exactly 0
    means "this case holds nothing", where `capacity or MAX_*` would silently
    read it as unset.
    """
    stated = capacity is not None
    max_regular = capacity if stated else MAX_REGULAR
    max_beanie = capacity if stated else MAX_BEANIE

    # Latitude only on the default. A stated capacity is exact — see the
    # note on OVERFILL_ALLOWANCE. A zero capacity holds nothing either way:
    # the allowance is slack on a real capacity, not a way in.
    allowance = 0 if stated else OVERFILL_ALLOWANCE
    beanie_allowance = 0 if stated else BEANIE_OVERFILL_ALLOWANCE
    limit_regular = max_regular + allowance if max_regular > 0 else 0
    limit_beanie = max_beanie + beanie_allowance if max_beanie > 0 else 0

    # Type exclusivity: a case holds beanies OR regular hats, never both.
    has_beanies = beanie_count > 0
    has_regular = regular_count > 0

    return Acceptance(
        accepts_regular=not has_beanies and regular_count < limit_regular,
        accepts_beanie=not has_regular and beanie_count < limit_beanie,
        free_regular=max(0, max_regular - regular_count),
        free_beanie=max(0, max_beanie - beanie_count),
        max_regular=max_regular,
        max_beanie=max_beanie,
        overfull_regular=regular_count > max_regular,
        overfull_beanie=beanie_count > max_beanie,
        limit_regular=limit_regular,
        limit_beanie=limit_beanie,
    )
