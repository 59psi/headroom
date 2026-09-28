/**
 * The roll-ups the Stats and Valuation pages both show, over `lib/valuation`.
 *
 * Each page carried its own copy of each: the "what the estimate rests on"
 * rows (identical but for how the unvalued row read), the top-ten "most
 * valuable" (identical), and two implementations of "sum what the hats are
 * worth by some key" — `valueBy` on Stats, `bucketize` on Valuation. The
 * valuation RULE had been made one function precisely because three copies
 * of it drifted; the views over it were drifting the same way.
 */
import type { HatRead } from '../types';
import { plural } from './format';
import { BASIS_LABEL, costOf, money, valueHat, type CollectionValuation, type ValueBasis } from './valuation';

/** Strongest basis first — the order both pages list them in. */
const BASIS_ORDER: readonly ValueBasis[] = ['manual', 'comp', 'retail', 'category', 'none'];

export interface BasisRow {
  label: string;
  value: number;
  display: string;
}

/**
 * One row per basis that any hat rests on: how many hats, and what they add
 * up to. The unvalued row has no total — it is the count left OUT of every
 * total — and says so.
 */
export function basisRows(valuation: CollectionValuation): BasisRow[] {
  return BASIS_ORDER
    .map(b => {
      const { count, total } = valuation.byBasis[b];
      return {
        label: BASIS_LABEL[b],
        value: count,
        display: b === 'none'
          ? `${plural(count, 'hat')} · not counted`
          : `${plural(count, 'hat')} · ${money(total)}`,
      };
    })
    .filter(r => r.value > 0);
}

/** The `n` hats worth the most, by the one valuation rule. Unvalued hats are left out, never ranked as $0. */
export function topValued(hats: readonly HatRead[], n = 10): HatRead[] {
  return hats
    .map(h => ({ h, value: valueHat(h).value }))
    .filter((x): x is { h: HatRead; value: number } => x.value != null)
    .sort((a, b) => b.value - a.value)
    .slice(0, n)
    .map(x => x.h);
}

/** Hats grouped by a key, with what they cost and what they are worth. */
export interface Bucket {
  /** The value grouped on — for a link, the stored enum, never the label. */
  key: string;
  /** What a person reads. */
  label: string;
  count: number;
  /** Paid, over the `paidCount` hats with a price on record. */
  paid: number;
  paidCount: number;
  /** Estimated worth, over the `valuedCount` hats that could be valued. */
  value: number;
  valuedCount: number;
}

/**
 * Group hats by `keyFn` and total each group, most valuable first. Hats with
 * no value for the key are left out. `labelFn` turns a key into words — the
 * server's label for an enum (`useHatLabels`), not the key with its
 * underscores swapped out.
 */
export function bucketize(
  hats: readonly HatRead[],
  keyFn: (h: HatRead) => string | null | undefined,
  labelFn: (key: string) => string = k => k,
): Bucket[] {
  const map = new Map<string, Bucket>();
  for (const h of hats) {
    const key = keyFn(h);
    if (!key) continue;
    const bucket = map.get(key) ?? {
      key, label: labelFn(key), count: 0, paid: 0, paidCount: 0, value: 0, valuedCount: 0,
    };
    bucket.count += 1;
    const paid = costOf(h);
    if (paid != null) { bucket.paid += paid; bucket.paidCount += 1; }
    const { value } = valueHat(h);
    if (value != null) { bucket.value += value; bucket.valuedCount += 1; }
    map.set(key, bucket);
  }
  return Array.from(map.values()).sort((a, b) => b.value - a.value || b.count - a.count);
}
