import type { QueryClient } from '@tanstack/react-query';

/**
 * Invalidate everything a hat change is visible in.
 *
 * Adding, deleting, disposing, restoring, re-assigning or wearing a hat all
 * change more than the hat: `['cases']` carries `hat_count` / `beanie_count`,
 * `['case', displayId]` carries the case's own hat list, and `['rooms']`
 * carries per-room counts. Each mutation used to pick its own subset — mostly
 * just `['hats']` — so a disposed hat kept occupying its slot on the Cases page
 * and inside the case for the 30s `staleTime`, which reads as the app losing
 * track of where things are.
 *
 * `['case']` is deliberately the bare prefix: TanStack matches query keys by
 * prefix, so it covers every open case detail without the caller having to know
 * which `displayId` is mounted.
 */
export function invalidateHatViews(qc: QueryClient, hatId?: number) {
  const keys: unknown[][] = [['hats'], ['cases'], ['case'], ['rooms']];
  if (hatId !== undefined) keys.push(['hat', hatId]);
  return Promise.all(keys.map(queryKey => qc.invalidateQueries({ queryKey })));
}
