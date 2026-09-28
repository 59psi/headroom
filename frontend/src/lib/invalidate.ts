import type { QueryClient } from '@tanstack/react-query';
import { qk } from './queryKeys';

type Key = readonly unknown[];

/**
 * Invalidate several key lists as ONE set — each key once.
 *
 * A mutation that changes two areas (a retry changes the analysis views AND
 * the hat views) used to call two helpers whose lists overlap, and TanStack
 * answers a second invalidation of an active query by canceling the refetch
 * the first one started and issuing another: one wasted request per shared
 * key, every time.
 */
export function invalidateAll(qc: QueryClient, ...lists: readonly Key[][]) {
  const seen = new Map<string, Key>();
  for (const k of lists.flat()) seen.set(JSON.stringify(k), k);
  return Promise.all([...seen.values()].map(queryKey => qc.invalidateQueries({ queryKey })));
}

/**
 * The keys a hat change is visible in — exported so the test can hold the
 * list to what it claims, and so nothing else has to restate it.
 *
 * Adding, deleting, disposing, restoring, re-assigning or wearing a hat all
 * change more than the hat: `cases()` carries `hat_count` / `beanie_count`,
 * `case(displayId)` carries the case's own hat list, and `rooms()` carries
 * per-room counts. Each mutation used to pick its own subset — mostly just
 * `['hats']` — so a disposed hat kept occupying its slot on the Cases page and
 * inside the case for the 30s `staleTime`, which reads as the app losing track
 * of where things are.
 *
 * **Every list that shows hats is on it**, not only the ones the collection
 * tabs render. Search results and duplicate groups carry each hat's case and
 * room, and exclude disposed hats — they were missing, so a hat marked sold
 * from a search stayed in that search when you pressed Back. The guest and
 * share views list hats with their room. The shared-price and frozen-price
 * reports list active hats by shelf id, and the recent-errors card captions
 * each failure with one.
 *
 * **Container mutations use this too**, and must: creating or moving a CASE
 * changes `RoomRead.case_count` and a room's `cases` list, and renaming or
 * deleting a ROOM changes the `room_name` printed on every hat card and the
 * room a loose hat is filed under. One list, or the two drift and only one of
 * them gets fixed.
 *
 * The container keys are the bare PREFIXES: TanStack matches query keys by
 * prefix, so `case()` covers every open case detail without the caller having
 * to know which `displayId` is mounted, and `search.all()` every search.
 * `room()` is a SIBLING of `rooms()`, not covered by it — "rooms" is not a
 * prefix of "room" — which is why both are named.
 *
 * `hat(hatId)` refreshes the hat DETAIL page. A caller that knows which hat
 * changed passes its id and narrows to that one; the whole-collection callers
 * (re-price all, unlink all, fill from purchases, a case moved between rooms)
 * pass none and get the bare `hat()` PREFIX, which covers every cached hat
 * page. Those callers left every open hat page stale for the 30s staleTime
 * before this key existed.
 */
export function hatViewKeys(hatId?: number): Key[] {
  return [
    qk.hats(), qk.cases(), qk.case(), qk.rooms(), qk.room(),
    qk.search.all(), qk.duplicates(), qk.guest.all(), qk.publicShare(),
    qk.admin.sharedPrices(), qk.admin.frozenPrices(), qk.admin.recentErrors(),
    qk.hat(hatId),
  ];
}

/** Invalidate everything a hat change is visible in (see `hatViewKeys`). */
export function invalidateHatViews(qc: QueryClient, hatId?: number) {
  return invalidateAll(qc, hatViewKeys(hatId));
}

/**
 * Everything a re-queued analysis changes, apart from the hats themselves.
 *
 * A retry or a re-run moves hats to `pending` and CLEARS their failure text,
 * so the queue's backlog, the failure groups, any open run log (a retry
 * re-tags the hats it queues), the recent-errors list AND the nav badge's
 * count all just changed. The last two are SIBLING keys —
 * `recent-errors` does not prefix `recent-errors-count` — and the queue card
 * used to refresh neither: after "Retry 2 hats" the badge went on counting
 * failures that were already queued. The recent-errors card and the queue
 * card run the same operation, so they share this rather than each keeping
 * a list. Both also change hats, so they invalidate this together with
 * `hatViewKeys` through `invalidateAll`.
 */
export function analysisViewKeys(): Key[] {
  return [
    qk.admin.analysisQueue(), qk.admin.analysisFailures(), qk.admin.analysisJob(),
    qk.admin.recentErrors(), qk.admin.recentErrorsCount(),
  ];
}

/**
 * The free-text vocabularies a hat save can EXTEND.
 *
 * `GET /api/meta/constructions` and `/collections` suggest what is already in
 * use, so a construction or collection typed for the first time belongs in the
 * next form's picker — and did not appear there until the 30s `staleTime` ran
 * out, which on the Add page (save, tap Add again) reads as the value having
 * not been kept. Sibling keys of nothing above; called by both hat forms and
 * by the construction audit, which rewrites the values wholesale.
 */
export function invalidateHatVocabulary(qc: QueryClient) {
  qc.invalidateQueries({ queryKey: qk.meta.constructions() });
  qc.invalidateQueries({ queryKey: qk.meta.collections() });
}

/**
 * Keys DERIVED from purchase→hat matching, which live on other cards.
 *
 * Matching is run from four places — three in the Purchases card (import,
 * re-run matching, unlink all) and the "Fill from purchase history" offer on
 * the shared-prices card — and every one of them changes what the
 * shared-price report and the "unclaimed colorways" offer are describing:
 * matching writes colorways and prices, which is exactly what those two group
 * and count. The purchase list itself is here too, so the shared-prices
 * card's fill cannot leave the Purchases card showing rows as unlinked.
 *
 * They are SIBLING keys, covered by nothing the Purchases card already
 * invalidates. Left alone, the offer went on advertising "Fill 17 from
 * purchase history" straight after the button that consumed the backlog — the
 * same class as the `['admin','recent-errors']` / `-count` trap: sibling keys,
 * where invalidating one never reaches the other because invalidation matches
 * by prefix. One helper because four call sites cannot be relied on to keep the
 * list in step — the fourth hand-rolled the same two lines until 2.78.
 */
export function invalidatePurchaseDerived(qc: QueryClient) {
  qc.invalidateQueries({ queryKey: qk.admin.purchases() });
  qc.invalidateQueries({ queryKey: qk.admin.unclaimedPurchases() });
  qc.invalidateQueries({ queryKey: qk.admin.sharedPrices() });
}
