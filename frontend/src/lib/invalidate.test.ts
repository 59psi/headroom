import { describe, it, expect, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import {
  analysisViewKeys,
  hatViewKeys,
  invalidateAll,
  invalidateHatViews,
  invalidateHatVocabulary,
  invalidatePurchaseDerived,
} from './invalidate';
import { qk } from './queryKeys';

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

/**
 * A REAL QueryClient holding one entry per key, so the assertion is about what
 * TanStack's prefix matching actually reaches — not about which arrays the
 * helper happened to pass. Returns whether each seeded key was invalidated.
 */
async function reached(keys: readonly (readonly unknown[])[], act: (qc: QueryClient) => unknown) {
  const qc = new QueryClient();
  for (const k of keys) qc.setQueryData(k, { seeded: true });
  await act(qc);
  return keys.map(k => [JSON.stringify(k), qc.getQueryState(k)?.isInvalidated ?? false]);
}

const hasHatPrefixKey = (calls: unknown[][]) =>
  calls.some(k => k.length === 2 && k[0] === 'hat');

describe('invalidateHatViews', () => {
  it('reaches every list a hat is shown in — the collection, containers, search, duplicates, public views, reports', async () => {
    // The keys as the pages build them, not as the helper spells its prefixes.
    const shown = [
      qk.hats(), qk.hatsDisposed(), qk.hat(1), qk.cases(), qk.case('A-001'),
      qk.rooms(), qk.room(2),
      // A disposed hat stayed in these for the 30s staleTime: the search you
      // came from still listed it after "Mark as sold".
      qk.search.text('odysea', false, null, 'major'), qk.search.color('#000000', null),
      // The pre-factory search key shape, which a page may still use.
      ['search', 'odysea', false, null, 'major'],
      qk.duplicates(),
      qk.guest.collection('', 'major'), qk.guest.hat(1), qk.publicShare('tok'),
      qk.admin.sharedPrices(), qk.admin.frozenPrices(), qk.admin.recentErrors(),
    ];
    const result = await reached(shown, qc => invalidateHatViews(qc, 1));
    expect(result.filter(([, hit]) => !hit)).toEqual([]);
  });

  it('leaves unrelated keys alone', async () => {
    const unrelated = [qk.meta.styles(), qk.settings.apiKey(), qk.admin.backups(), qk.hat(2)];
    const result = await reached(unrelated, qc => invalidateHatViews(qc, 1));
    expect(result.filter(([, hit]) => hit)).toEqual([]);
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

describe('analysisViewKeys', () => {
  it('refreshes the queue card AND both sibling recent-errors keys, including the nav badge', async () => {
    const keys = [
      qk.admin.analysisQueue(), qk.admin.analysisFailures(), qk.admin.analysisJob(7),
      qk.admin.recentErrors(), qk.admin.recentErrorsCount(),
    ];
    const result = await reached(keys, qc => invalidateAll(qc, analysisViewKeys()));
    expect(result.filter(([, hit]) => !hit)).toEqual([]);
  });
});

describe('invalidateAll', () => {
  it('invalidates a key two lists share only once — a second call cancels and repeats the refetch', async () => {
    const { qc, calls } = fakeClient();
    await invalidateAll(qc, analysisViewKeys(), hatViewKeys(3));
    const shown = calls.map(k => JSON.stringify(k));
    expect(shown.filter(k => k === JSON.stringify(qk.admin.recentErrors()))).toHaveLength(1);
    expect(new Set(shown).size).toBe(shown.length);
  });
});

describe('invalidatePurchaseDerived', () => {
  it('invalidates the purchase list and the sibling keys derived from matching', () => {
    const { qc, calls } = fakeClient();
    invalidatePurchaseDerived(qc);
    expect(calls).toContainEqual(['admin', 'purchases']);
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
