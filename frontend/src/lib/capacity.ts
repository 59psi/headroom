/**
 * Default case capacities, for the UI to describe.
 *
 * `services/capacity.py` is the authority — it enforces these on write and
 * publishes the per-case numbers the pickers render. This module exists only
 * so the *default*, which no particular case can report, is stated once
 * instead of typed into a placeholder string.
 *
 * It was typed into a placeholder string, in two files, and read
 * "Default: 4 regular / 6 beanies" — wrong in both digits, for long enough
 * that the physical article (melin's own order lines call it a "3 Hat Travel
 * Case") disagreed with the app on the screen where you create one.
 *
 * `tests/test_valuation_parity.py`'s sibling, `test_capacity_parity.py`,
 * reads these numbers back out of this file and fails if they drift from the
 * Python. That mechanism already existed in this repo for exactly this class
 * of mistake; this is the second constant to need it.
 */

/** Regular hats in a default case. The physical article holds three. */
export const DEFAULT_REGULAR_CAPACITY = 3;

/** Beanies in a default case — they pack far smaller. */
export const DEFAULT_BEANIE_CAPACITY = 6;

/**
 * How far past nominal a default case may be crammed.
 *
 * A fourth hat does go in; it just isn't how the case is meant to be loaded,
 * so it is accepted on write and reported as *overfull*. Beanies get none —
 * 6 is the owner stating how many belong in a case rather than a name on a
 * box, and a stated number is exact.
 */
export const REGULAR_OVERFILL_ALLOWANCE = 1;
export const BEANIE_OVERFILL_ALLOWANCE = 0;

/**
 * The placeholder both case forms show. Built from the constants, not typed.
 *
 * Says the nominal figure AND the squeeze, because both are true and quoting
 * only one is what the old hand-written string got wrong in both directions:
 * it read "4 regular" (the squeeze limit, presented as the default) and
 * "6 beanies" (neither).
 */
export const CAPACITY_PLACEHOLDER =
  `Default: ${DEFAULT_REGULAR_CAPACITY} regular ` +
  `(${DEFAULT_REGULAR_CAPACITY + REGULAR_OVERFILL_ALLOWANCE} at a squeeze) ` +
  `/ ${DEFAULT_BEANIE_CAPACITY} beanies`;
