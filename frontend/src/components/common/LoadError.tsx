import type { ReactNode } from 'react';
import { describeError } from './ErrorNote';

/** What `LoadError` needs of a query — a TanStack `useQuery` result has all of it. */
export interface Retryable {
  isError: boolean;
  error: unknown;
  isFetching: boolean;
  refetch: () => unknown;
}

/**
 * A page whose data did not load: what failed, why, and a retry in place.
 *
 * Five list pages carried a copy of this block and two did not: Cases said
 * "Reload to try again" with no button (a reload restarts the whole app to
 * refetch one list), and Rooms offered only "Back". A failed fetch is also
 * the one place a page must NOT fall through to its empty state — "No hats
 * yet · Add first hat" over a 500 is a confident wrong answer with a call to
 * action — so every page that owns its data renders this instead.
 *
 * The retry refetches every query handed in (a refetch of one that did not
 * fail costs a request and changes nothing), and the reason is the first
 * failure's — the page names WHAT failed, the server says why.
 */
export function LoadError({
  what,
  queries,
  className = '',
}: {
  /** The sentence for what did not load: "Couldn't load your cases." */
  what: ReactNode;
  queries: readonly Retryable[];
  className?: string;
}) {
  const failed = queries.find(q => q.isError);
  const retrying = queries.some(q => q.isFetching);
  return (
    <div className={`alert alert-danger hr-load-error${className ? ` ${className}` : ''}`} role="alert">
      <span>
        {what}
        {failed && <span className="hr-load-error-why"> {describeError(failed.error)}</span>}
      </span>
      <button
        type="button"
        className="btn btn-sm btn-outline-secondary"
        onClick={() => { for (const q of queries) void q.refetch(); }}
        disabled={retrying}
      >{retrying ? 'Retrying…' : 'Try again'}</button>
    </div>
  );
}
