import type { QueryClient } from '@tanstack/react-query';

/**
 * Invalidate everything a placement change is visible in.
 *
 * Adding, deleting, disposing, restoring, re-assigning or wearing a hat all
 * change more than the hat: `['cases']` carries `hat_count` / `beanie_count`,
 * `['case', displayId]` carries the case's own hat list, and `['rooms']`
 * carries per-room counts. Each mutation used to pick its own subset — mostly
 * just `['hats']` — so a disposed hat kept occupying its slot on the Cases page
 * and inside the case for the 30s `staleTime`, which reads as the app losing
 * track of where things are.
 *
 * **Container mutations use this too**, and must: creating or moving a CASE
 * changes `RoomRead.case_count` and a room's `cases` list, and renaming or
 * deleting a ROOM changes the `room_name` printed on every hat card and the
 * room a loose hat is filed under. Those four mutations each picked their own
 * subset as well — case create/edit invalidated only `['cases']`, room
 * mutations never touched `['hats']` — which is the identical bug one level
 * up. One list, or the two drift and only one of them gets fixed.
 *
 * `['case']` is deliberately the bare prefix: TanStack matches query keys by
 * prefix, so it covers every open case detail without the caller having to know
 * which `displayId` is mounted.
 */
export function invalidateHatViews(qc: QueryClient, hatId?: number) {
  // `['room']` is a SIBLING of `['rooms']`, not covered by it — TanStack
  // matches by prefix, and "rooms" is not a prefix of "room". The room view
  // lists a room's loose hats, so a hat moving into or out of a room changes
  // it; without this the page would keep showing the hat where it used to be
  // for the whole 30s staleTime. Same shape of trap as
  // `['admin','recent-errors']` vs `['admin','recent-errors-count']`.
  const keys: unknown[][] = [['hats'], ['cases'], ['case'], ['rooms'], ['room']];
  if (hatId !== undefined) keys.push(['hat', hatId]);
  return Promise.all(keys.map(queryKey => qc.invalidateQueries({ queryKey })));
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
  qc.invalidateQueries({ queryKey: ['meta', 'constructions'] });
  qc.invalidateQueries({ queryKey: ['meta', 'collections'] });
}

/**
 * Keys DERIVED from purchase→hat matching, which live on other cards.
 *
 * Matching is run from four places — three in the Purchases card (import,
 * re-run matching, unlink all) and the "Fill from purchase history" offer on
 * the shared-prices card — and every one of them changes what the
 * shared-price report and the "unclaimed colorways" offer are describing:
 * matching writes colorways and prices, which is exactly what those two group
 * and count.
 *
 * They are SIBLING keys, covered by nothing the Purchases card already
 * invalidates. Left alone, the offer went on advertising "Fill 17 from
 * purchase history" straight after the button that consumed the backlog — the
 * same class as the `['admin','recent-errors']` / `-count` trap CLAUDE.md
 * names. One helper because four call sites cannot be relied on to keep the
 * list in step — the fourth hand-rolled the same two lines until 2.78.
 */
export function invalidatePurchaseDerived(qc: QueryClient) {
  qc.invalidateQueries({ queryKey: ['admin', 'unclaimed-purchases'] });
  qc.invalidateQueries({ queryKey: ['admin', 'shared-prices'] });
}
