/**
 * The valuation rule, pinned.
 *
 * This module previously existed as three hand-written copies that had already
 * drifted — the home page's caption described multipliers that were, by then,
 * being applied to almost none of the collection. Tests here because the
 * failure mode is silent: a wrong total still renders as a confident number,
 * and nobody can eyeball whether $7,944 is right.
 */
import { describe, expect, it } from 'vitest';
import {
  ASK_TO_SOLD, CONDITION_VS_MARKET, RETAIL_RETENTION,
  costOf, realizedTotals, valueCollection, valueHat,
} from './valuation';
import type { HatRead } from '../types';

/** A hat with nothing priced. Tests set only the fields they're about. */
function hat(over: Partial<HatRead> = {}): HatRead {
  return {
    id: 1,
    case_id: null,
    position_in_case: null,
    display_id: 'A-001-01',
    case_display_id: null,
    case_type: null,
    photo_path: null,
    original_path: null,
    thumb_path: null,
    condition: 'new_with_tags',
    date_last_worn: null,
    wear_count: 0,
    size: 'classic',
    style: 'a_game',
    is_beanie: false,
    colors: [],
    room_id: null,
    room_name: null,
    brand: null,
    logo_detected: null,
    artist_series: null,
    construction: null,
    hydrolite: false,
    hydro: false,
    model_name: null,
    colorway: null,
    purchase_price: null,
    purchased_at: null,
    model_confidence: null,
    style_descriptor: null,
    design_notes: null,
    estimated_new_price: null,
    estimated_new_price_source: null,
    resale_price: null,
    resale_price_source: null,
    resale_price_url: null,
    resale_checked_at: null,
    resale_price_scope: null,
    analysis_status: null,
    analysis_stage: null,
    analysis_job_id: null,
    analysis_error: null,
    analyzed_at: null,
    disposed_at: null,
    disposed_via: null,
    disposed_price: null,
    disposed_to: null,
    disposed_notes: null,
    ebay_avg_price: null,
    ebay_median_price: null,
    ebay_listing_count: null,
    ebay_search_url: null,
    ebay_checked_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...over,
  };
}

describe('valueHat — signal priority', () => {
  it('uses a manually entered price exactly as given', () => {
    const v = valueHat(hat({ resale_price: 120, resale_price_scope: 'manual', condition: 'worn' }));
    expect(v.basis).toBe('manual');
    // Emphatically NOT discounted: a person's own number is not an asking
    // price scraped off a marketplace, and haircutting it would mean the app
    // silently disagreeing with an explicit instruction.
    expect(v.value).toBe(120);
  });

  it('discounts a model-scoped market median for ask-vs-sale and condition', () => {
    const v = valueHat(hat({ resale_price: 100, resale_price_scope: 'model', condition: 'worn' }));
    expect(v.basis).toBe('comp');
    expect(v.value).toBeCloseTo(100 * ASK_TO_SOLD * CONDITION_VS_MARKET.worn, 6);
    // The whole point of the rework: this must land well under the raw ask.
    expect(v.value!).toBeLessThan(100);
  });

  it('values the same ask higher for a better-condition hat', () => {
    const worn = valueHat(hat({ resale_price: 100, resale_price_scope: 'model', condition: 'worn' }));
    const tagged = valueHat(hat({ resale_price: 100, resale_price_scope: 'model', condition: 'new_with_tags' }));
    // Before the rework both were 100 — the feed's median went straight in and
    // condition was ignored entirely whenever a market price existed.
    expect(tagged.value!).toBeGreaterThan(worn.value!);
  });

  it('falls back to a share of retail when no model comps exist', () => {
    const v = valueHat(hat({ estimated_new_price: 200, condition: 'new' }));
    expect(v.basis).toBe('retail');
    expect(v.value).toBeCloseTo(200 * RETAIL_RETENTION.new, 6);
  });

  it('prefers retail over a category median, because retail is about THIS hat', () => {
    const v = valueHat(hat({
      estimated_new_price: 200,
      resale_price: 900,
      resale_price_scope: 'category',
      condition: 'new',
    }));
    expect(v.basis).toBe('retail');
    // A category median is the price level for the whole style. Letting the
    // 900 win would hand every hat in the category the same inflated number.
    expect(v.value).toBeCloseTo(200 * RETAIL_RETENTION.new, 6);
  });

  it('uses a category median only as a last resort, and says so', () => {
    const v = valueHat(hat({ resale_price: 90, resale_price_scope: 'category' }));
    expect(v.basis).toBe('category');
    expect(v.value).toBeCloseTo(90 * ASK_TO_SOLD * CONDITION_VS_MARKET.new_with_tags, 6);
  });

  it('returns null — not zero — when nothing supports a number', () => {
    const v = valueHat(hat());
    expect(v.basis).toBe('none');
    expect(v.value).toBeNull();
  });
});

describe('valueCollection', () => {
  it('excludes unvalued hats from totals instead of counting them as $0', () => {
    const totals = valueCollection([
      hat({ id: 1, estimated_new_price: 100, condition: 'new_with_tags' }),
      hat({ id: 2 }),
      hat({ id: 3 }),
    ]);
    expect(totals.total).toBe(3);
    expect(totals.valued).toBe(1);
    expect(totals.unvalued).toBe(2);
    expect(totals.marketTotal).toBeCloseTo(100 * RETAIL_RETENTION.new_with_tags, 6);
    // Two priceless hats must not drag an average down as though they were free.
    expect(totals.byBasis.none.count).toBe(2);
    expect(totals.byBasis.none.total).toBe(0);
  });

  it('computes retention over the hats counted in BOTH totals', () => {
    const totals = valueCollection([
      hat({ id: 1, estimated_new_price: 100, condition: 'new_with_tags' }),
      // Valued, but with no retail figure — it must not inflate the ratio's
      // numerator against a denominator it never contributed to.
      hat({ id: 2, resale_price: 500, resale_price_scope: 'model' }),
    ]);
    expect(totals.retentionPct).toBe(Math.round(RETAIL_RETENTION.new_with_tags * 100));
  });

  it('reports unrealized gain only across hats with both a cost and a value', () => {
    const totals = valueCollection([
      hat({ id: 1, purchase_price: 50, estimated_new_price: 200, condition: 'new_with_tags' }),
      hat({ id: 2, purchase_price: 40 }),   // no value → outside the comparison
    ]);
    expect(totals.spentTotal).toBe(90);
    expect(totals.spentCount).toBe(2);
    expect(totals.unrealizedGain).toBeCloseTo(200 * RETAIL_RETENTION.new_with_tags - 50, 6);
  });

  it('counts hats with no purchase price as a gap, not as free', () => {
    const totals = valueCollection([
      hat({ id: 1, purchase_price: 60 }),
      hat({ id: 2 }),
    ]);
    expect(totals.spentTotal).toBe(60);
    expect(totals.costUnknown).toBe(1);
  });

  it('has no gain to report when nothing has a purchase price', () => {
    const totals = valueCollection([hat({ id: 1, estimated_new_price: 100 })]);
    expect(totals.unrealizedGain).toBeNull();
  });
});

describe('costOf', () => {
  it('treats a zero price as unknown rather than as free', () => {
    expect(costOf(hat({ purchase_price: 0 }))).toBeNull();
    expect(costOf(hat({ purchase_price: 45 }))).toBe(45);
  });
});

describe('realizedTotals', () => {
  it('counts only sales, and nets off cost only where cost is known', () => {
    const r = realizedTotals([
      hat({ id: 1, disposed_via: 'sold', disposed_price: 120, purchase_price: 80 }),
      hat({ id: 2, disposed_via: 'sold', disposed_price: 60 }),   // cost unknown
      hat({ id: 3, disposed_via: 'gifted' }),
    ]);
    expect(r.sold).toBe(2);
    expect(r.proceeds).toBe(180);
    expect(r.otherDisposals).toBe(1);
    // Only hat 1 has both figures, so the net is 120 − 80. Including hat 2's
    // proceeds with no cost to subtract would report a $60 profit on a hat
    // that might have been bought for $200.
    expect(r.soldWithKnownCost).toBe(1);
    expect(r.netGain).toBe(40);
  });

  it('reports no net gain when no sold hat has a known cost', () => {
    const r = realizedTotals([hat({ disposed_via: 'sold', disposed_price: 99 })]);
    expect(r.proceeds).toBe(99);
    expect(r.netGain).toBeNull();
  });
});
