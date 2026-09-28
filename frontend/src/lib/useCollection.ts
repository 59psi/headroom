import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { listAllHats, listDisposedHats } from '../api/hats';
import { listCases } from '../api/cases';
import { qk } from './queryKeys';

/**
 * The whole collection — active hats, the ones that left, and the cases —
 * for the pages that total it: Stats and Valuation.
 *
 * Both fetched the same three lists and guarded them the same two ways, in
 * copies that had to stay in step:
 *
 * - **A failure is `failed`, never an empty collection.** `?? []` turns a 500
 *   or a dropped connection into "$0 across 0 hats", a confident wrong
 *   answer — the exact thing `valueHat` returns null rather than 0 to avoid.
 *   `queries` is what `LoadError` retries.
 * - **`loading` until ALL three have arrived.** Rendering before the disposed
 *   hats or the cases landed showed a Realized tile of "$0 · 0 sold" and a
 *   total without its cases line, then changed them under the reader.
 */
export function useCollection() {
  const hatsQ = useQuery({ queryKey: qk.hats(), queryFn: listAllHats });
  const disposedQ = useQuery({ queryKey: qk.hatsDisposed(), queryFn: listDisposedHats });
  const casesQ = useQuery({ queryKey: qk.cases(), queryFn: listCases });

  const hats = useMemo(() => hatsQ.data ?? [], [hatsQ.data]);
  const disposed = useMemo(() => disposedQ.data ?? [], [disposedQ.data]);
  const cases = useMemo(() => casesQ.data ?? [], [casesQ.data]);
  const queries = [hatsQ, disposedQ, casesQ];

  return {
    hats,
    disposed,
    cases,
    queries,
    failed: queries.some(q => q.isError),
    loading: queries.some(q => q.isLoading),
  };
}
