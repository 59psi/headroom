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

# Defaults when a case carries no explicit `capacity`. Beanies pack smaller, so
# more fit in the same physical case.
MAX_REGULAR = 4
MAX_BEANIE = 6


@dataclass(frozen=True)
class Acceptance:
    """Whether a case can take one more hat of each kind, and how many more."""

    accepts_regular: bool
    accepts_beanie: bool
    free_regular: int
    free_beanie: int
    max_regular: int
    max_beanie: int


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
    max_regular = MAX_REGULAR if capacity is None else capacity
    max_beanie = MAX_BEANIE if capacity is None else capacity

    # Type exclusivity: a case holds beanies OR regular hats, never both.
    has_beanies = beanie_count > 0
    has_regular = regular_count > 0

    free_regular = max(0, max_regular - regular_count)
    free_beanie = max(0, max_beanie - beanie_count)

    return Acceptance(
        accepts_regular=not has_beanies and free_regular > 0,
        accepts_beanie=not has_regular and free_beanie > 0,
        free_regular=free_regular,
        free_beanie=free_beanie,
        max_regular=max_regular,
        max_beanie=max_beanie,
    )
