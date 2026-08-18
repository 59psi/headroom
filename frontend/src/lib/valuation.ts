/**
 * What the collection is worth — one rule, used everywhere.
 *
 * There were three copies of this: HomePage, ValuationPage, and the server's
 * inventory report. They had already drifted, and the drift was not cosmetic —
 * the home page told you "Resale = manual override, else condition-based
 * estimate (NWT 65% · New 45% · Worn 30%)" while actually reporting something
 * else entirely, because by then `resale_price` was being filled automatically
 * by the melinrecap feed on every analysis. That is how the summary could read
 * "92% of new": almost nothing was going through the multipliers the caption
 * named.
 *
 * ## The thing to understand about the inputs
 *
 * **Neither price feed knows what anything sold for.** The eBay integration
 * uses the Browse API, which returns *currently listed* items — its own module
 * docstring says so. The melinrecap median is computed from `live` listings.
 * Both are ASKING prices: what sellers want, filtered by survivorship, since
 * anything priced to move has already left the sample. Reporting their sum as
 * what a collection is worth overstates it twice — once for the spread between
 * ask and sale, and once because a median asking price is drawn from a pool of
 * mixed condition and gets applied to a hat whose condition we know exactly.
 *
 * So: start from the best signal available, then say out loud what it is.
 *
 * ## Signal order
 *
 * 1. `manual`   — a person typed a price. Used as-is; no adjustment. They know
 *                 something the feeds don't.
 * 2. `comp`     — median ask across listings matching this MODEL. A real
 *                 comparable. Adjusted for ask→sale and for condition.
 * 3. `retail`   — condition-based fraction of estimated new retail. No market
 *                 data for this hat, but the estimate is at least ABOUT this
 *                 hat, which beats a category average.
 * 4. `category` — median ask across every listing in the style category. This
 *                 is the price level of "an Odysea", not the value of this
 *                 Odysea; used only when there is nothing else, and reported
 *                 separately so a total resting on it can be recognised.
 * 5. `none`     — nothing supports a number. Counted, never guessed at, and
 *                 never quietly treated as $0 inside an average.
 */
import type { HatRead } from '../types';

/**
 * What the marketplace pays a seller, as a fraction of the sale price.
 *
 * Carried on every listing in `publicData.payoutInfo`, identical across all
 * 706 live listings sampled when this was written. A hat's market value and
 * what you end up holding are different numbers, and only the first was ever
 * shown: sell a $79 hat and $63 arrives, or $87 of brand credit.
 */
export const CASH_PAYOUT = 0.80;
export const CREDIT_PAYOUT = 1.10;

/**
 * Fraction of new retail retained, when there is no market signal at all.
 *
 * The original rule of thumb, kept — it was never the problem. The problem was
 * the caption claiming it applied when it mostly didn't.
 */
export const RETAIL_RETENTION: Record<string, number> = {
  new_with_tags: 0.65,
  new: 0.45,
  worn: 0.30,
};

/** Applied when a hat's condition isn't one of the three known values. */
const FALLBACK_RETENTION = 0.4;

export type ValueBasis = 'manual' | 'comp' | 'retail' | 'category' | 'none';

export interface HatValuation {
  /** Best estimate of what this hat fetches if sold today. Null means the
   *  record doesn't support a number — never coerce this to 0. */
  value: number | null;
  basis: ValueBasis;
  /** One line naming where the number came from, for display next to it. */
  explanation: string;
}

export const BASIS_LABEL: Record<ValueBasis, string> = {
  manual: 'Your price',
  comp: 'Model comps',
  retail: 'From retail',
  category: 'Category avg',
  none: 'Not valued',
};

const CONDITION_LABEL: Record<string, string> = {
  new_with_tags: 'new with tags',
  new: 'new',
  worn: 'worn',
};

function pct(n: number): string {
  return `${Math.round(n * 100)}%`;
}

/** What one hat is worth, and why. */
export function valueHat(h: HatRead): HatValuation {
  const ask = h.resale_price ?? 0;
  const retail = h.estimated_new_price ?? 0;
  const condLabel = CONDITION_LABEL[h.condition] ?? h.condition.replace(/_/g, ' ');

  if (h.resale_price_scope === 'manual' && ask > 0) {
    return { value: ask, basis: 'manual', explanation: 'Price you entered — used as given.' };
  }

  if (h.resale_price_scope === 'model' && ask > 0) {
    return {
      value: ask,
      basis: 'comp',
      explanation:
        h.resale_price_source
        ?? `Median price of comparable ${condLabel} listings for this model.`,
    };
  }

  if (retail > 0) {
    const retention = RETAIL_RETENTION[h.condition] ?? FALLBACK_RETENTION;
    return {
      value: retail * retention,
      basis: 'retail',
      explanation: `${pct(retention)} of estimated new retail, the rate for ${condLabel}.`,
    };
  }

  if (ask > 0) {
    return {
      value: ask,
      basis: 'category',
      explanation:
        'No comps for this model and no retail estimate — falls back to the ' +
        'median across the whole style category, which is a price level ' +
        'rather than a valuation of this hat.',
    };
  }

  return {
    value: null,
    basis: 'none',
    explanation: 'No price data yet — analyse the photo or enter a price to include it.',
  };
}

/** What was actually paid, when that is on record. */
export function costOf(h: HatRead): number | null {
  return h.purchase_price != null && h.purchase_price > 0 ? h.purchase_price : null;
}

export interface BasisTally { count: number; total: number }

export interface CollectionValuation {
  /** Hats fed in. */
  total: number;
  /** Hats a number could be produced for. */
  valued: number;
  /** Hats with nothing to value them by — excluded from every total below. */
  unvalued: number;
  /** Sum of `valueHat`, across `valued` hats only. */
  marketTotal: number;
  /** Sum of estimated new retail, across hats that have one. */
  retailTotal: number;
  retailCount: number;
  /** Sum of what was paid, across hats with a recorded price. */
  spentTotal: number;
  spentCount: number;
  /** Hats with no recorded purchase price — the gap in the cost basis. */
  costUnknown: number;
  /** marketTotal ÷ retailTotal, over hats counted in BOTH, or null.
   *  Restricted to the overlap because a ratio between two differently-sized
   *  populations isn't a percentage of anything. */
  retentionPct: number | null;
  /** marketTotal − spentTotal over hats present in BOTH, or null. */
  unrealizedGain: number | null;
  byBasis: Record<ValueBasis, BasisTally>;
}

function emptyTally(): Record<ValueBasis, BasisTally> {
  return {
    manual: { count: 0, total: 0 },
    comp: { count: 0, total: 0 },
    retail: { count: 0, total: 0 },
    category: { count: 0, total: 0 },
    none: { count: 0, total: 0 },
  };
}

/** Roll a set of hats up into the figures every summary view shows. */
export function valueCollection(hats: HatRead[]): CollectionValuation {
  const byBasis = emptyTally();
  let marketTotal = 0;
  let valued = 0;
  let retailTotal = 0;
  let retailCount = 0;
  let spentTotal = 0;
  let spentCount = 0;
  // Accumulated over the overlaps only, so the comparisons below stay honest
  // about comparing the same hats.
  let overlapMarketVsRetail = 0;
  let overlapRetail = 0;
  let overlapMarketVsCost = 0;
  let overlapCost = 0;

  for (const h of hats) {
    const { value, basis } = valueHat(h);
    const retail = h.estimated_new_price ?? 0;
    const cost = costOf(h);

    byBasis[basis].count += 1;
    if (value != null) {
      byBasis[basis].total += value;
      marketTotal += value;
      valued += 1;
    }
    if (retail > 0) {
      retailTotal += retail;
      retailCount += 1;
      if (value != null) {
        overlapMarketVsRetail += value;
        overlapRetail += retail;
      }
    }
    if (cost != null) {
      spentTotal += cost;
      spentCount += 1;
      if (value != null) {
        overlapMarketVsCost += value;
        overlapCost += cost;
      }
    }
  }

  return {
    total: hats.length,
    valued,
    unvalued: hats.length - valued,
    marketTotal,
    retailTotal,
    retailCount,
    spentTotal,
    spentCount,
    costUnknown: hats.length - spentCount,
    retentionPct: overlapRetail > 0
      ? Math.round((overlapMarketVsRetail / overlapRetail) * 100)
      : null,
    unrealizedGain: overlapCost > 0 ? overlapMarketVsCost - overlapCost : null,
    byBasis,
  };
}

export interface RealizedTotals {
  /** Hats disposed of by sale, with a price on record. */
  sold: number;
  /** Proceeds from those sales. */
  proceeds: number;
  /** What those same hats cost, over the subset where cost is known. */
  costOfSold: number;
  soldWithKnownCost: number;
  /** Proceeds − cost across the known-cost subset only, or null. */
  netGain: number | null;
  /** Disposed some other way (gifted, traded, lost, trashed). */
  otherDisposals: number;
}

/** Money actually realized from hats that have left the collection. */
export function realizedTotals(disposed: HatRead[]): RealizedTotals {
  let sold = 0;
  let proceeds = 0;
  let costOfSold = 0;
  let soldWithKnownCost = 0;
  let proceedsWithKnownCost = 0;
  let otherDisposals = 0;

  for (const h of disposed) {
    const price = h.disposed_price ?? 0;
    if (h.disposed_via === 'sold' && price > 0) {
      sold += 1;
      proceeds += price;
      const cost = costOf(h);
      if (cost != null) {
        costOfSold += cost;
        proceedsWithKnownCost += price;
        soldWithKnownCost += 1;
      }
    } else {
      otherDisposals += 1;
    }
  }

  return {
    sold,
    proceeds,
    costOfSold,
    soldWithKnownCost,
    netGain: soldWithKnownCost > 0 ? proceedsWithKnownCost - costOfSold : null,
    otherDisposals,
  };
}

/** `$1,234` — the app's one money format. Rounded; cents are noise at this scale. */
export function money(n: number): string {
  return `$${Math.round(n).toLocaleString()}`;
}

/** `$12.34` — for per-unit figures where rounding to the dollar loses the point. */
export function moneyPrecise(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
