import { describe, it, expect, vi } from 'vitest';
import type { QueryClient } from '@tanstack/react-query';
import {
  invalidateHatViews,
  invalidateHatVocabulary,
  invalidatePurchaseDerived,
} from './invalidate';

/** A QueryClient stub that records every queryKey passed to invalidateQueries. */
function fakeClient() {
  const calls: unknown[][] = [];
  const qc = {
    invalidateQueries: vi.fn(({ queryKey }: { queryKey: unknown[] }) => {
      calls.push(queryKey);
      return Promise.resolve();
    }),
  } as unknown as QueryClient;
  return { qc, calls };
}

const hasHatPrefixKey = (calls: unknown[][]) =>
  calls.some(k => k.length === 2 && k[0] === 'hat');

describe('invalidateHatViews', () => {
  it('refreshes every placement + container view a hat change is visible in', async () => {
    const { qc, calls } = fakeClient();
    await invalidateHatViews(qc);
    // `['room']` is a SIBLING of `['rooms']` (prefix matching does not cover it)
    // and `['case']` a bare prefix over every mounted case — dropping either
    // leaves a moved hat on a stale page. Assert the whole set, not a count.
    expect(calls).toEqual(
      expect.arrayContaining([['hats'], ['cases'], ['case'], ['rooms'], ['room']]),
    );
  });

  it('narrows the hat DETAIL key to the one hat when given its id', async () => {
    const { qc, calls } = fakeClient();
    await invalidateHatViews(qc, 42);
    expect(calls).toContainEqual(['hat', 42]);
    // A single-hat caller must NOT fire the bare prefix — that would be a wider
    // invalidation than it asked for. (Mutation: revert to always-bare.)
    expect(calls).not.toContainEqual(['hat']);
  });

  it('uses the bare ["hat"] prefix for a whole-collection change', async () => {
    const { qc, calls } = fakeClient();
    await invalidateHatViews(qc);
    // Re-price-all / unlink-all pass no id and must refresh EVERY open hat
    // detail page. (Mutation: drop the push, or narrow unconditionally.)
    expect(calls).toContainEqual(['hat']);
    expect(hasHatPrefixKey(calls)).toBe(false);
  });
});

describe('invalidatePurchaseDerived', () => {
  it('invalidates the sibling keys the Purchases card does not', () => {
    const { qc, calls } = fakeClient();
    invalidatePurchaseDerived(qc);
    expect(calls).toContainEqual(['admin', 'unclaimed-purchases']);
    expect(calls).toContainEqual(['admin', 'shared-prices']);
  });
});

describe('invalidateHatVocabulary', () => {
  it('invalidates the two meta vocabularies a hat save can extend', () => {
    const { qc, calls } = fakeClient();
    invalidateHatVocabulary(qc);
    expect(calls).toContainEqual(['meta', 'constructions']);
    expect(calls).toContainEqual(['meta', 'collections']);
  });
});
