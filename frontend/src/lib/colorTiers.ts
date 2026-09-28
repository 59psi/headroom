import type { ColorTag } from '../types';

/** One of the server's four tiers (`schemas/hat.ColorTier`). */
export type Tier = NonNullable<ColorTag['tier']>;

/**
 * How much of a hat a color covers — the server's four tiers, in the order a
 * palette lists them.
 */
export const COLOR_TIERS: ReadonlyArray<{ value: Tier; label: string }> = [
  { value: 'primary', label: 'Primary' },
  { value: 'secondary', label: 'Secondary' },
  { value: 'tertiary', label: 'Tertiary' },
  { value: 'accent', label: 'Accent' },
];

/** A select's string narrowed to a tier; anything else reads as primary, as
 *  the server reads an unknown stored tier. */
export function asTier(value: string): Tier {
  return COLOR_TIERS.find(t => t.value === value)?.value ?? 'primary';
}

/**
 * The tier a color added by hand starts at, from where it lands in the list.
 *
 * The same reading the analyzers give a palette (`color_extraction` labels its
 * first three primary, secondary, tertiary; anything after is a detail). The
 * Edit form used to stamp every added color `primary`, so a third color typed
 * in read "primary" on the hat page — a tier nobody chose. A starting point,
 * not a rule: the owner can pick another.
 */
export function tierForRank(rank: number): Tier {
  return COLOR_TIERS[Math.min(Math.max(rank, 1), COLOR_TIERS.length) - 1].value;
}
