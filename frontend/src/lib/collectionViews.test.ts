/**
 * The roll-ups Stats and Valuation both show — one copy now, so one test.
 */
import { describe, expect, it } from 'vitest';
import { hatFixture } from '../test/fixtures';
import { basisRows, bucketize, topValued } from './collectionViews';
import { valueCollection } from './valuation';

describe('basisRows', () => {
  it('agrees in number — "1 hat", never "1 hats" — and leaves the unvalued out of every total', () => {
    const rows = basisRows(valueCollection([
      hatFixture({ id: 1, resale_price: 120, resale_price_scope: 'manual' }),
      hatFixture({ id: 2 }),
    ]));
    expect(rows.map(r => r.display)).toEqual(['1 hat · $120', '1 hat · not counted']);
  });
});

describe('bucketize', () => {
  it('keeps the key it groups on apart from the words it shows', () => {
    const [b] = bucketize([hatFixture({ style: 'a_game', estimated_new_price: 100 })], h => h.style, () => 'A-Game');
    expect(b).toMatchObject({ key: 'a_game', label: 'A-Game', count: 1 });
  });
});

describe('topValued', () => {
  it('ranks by the one valuation rule and never ranks an unvalued hat as $0', () => {
    const top = topValued([
      hatFixture({ id: 1, estimated_new_price: 50 }),
      hatFixture({ id: 2 }),
      hatFixture({ id: 3, resale_price: 300, resale_price_scope: 'manual' }),
    ]);
    expect(top.map(h => h.id)).toEqual([3, 1]);
  });
});
