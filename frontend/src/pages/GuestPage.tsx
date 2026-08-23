import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router';
import { getGuestCollection } from '../api/guest';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { SharedCollectionGrid } from '../components/share/SharedCollectionGrid';
import { ColorScopePicker } from '../components/common/ColorScopePicker';

/**
 * Browsing the collection without an account.
 *
 * Public and outside the app shell, like the share-link page — a guest has no
 * session, so the bottom nav's tabs would all bounce them to the login screen.
 *
 * Search is server-side rather than filtering a fetched list, because the
 * server is where the real multi-term search lives. Filtering client-side
 * would be a second, worse search that quietly stopped matching what the
 * owner's search matches.
 */
export function GuestPage() {
  // The submitted term lives in the URL, not in state. Opening a hat and
  // pressing Back re-mounts this page, and component state does not survive
  // that — you came back to the whole collection with an empty box, having
  // lost the search you were part-way through. In the URL it is restored by
  // the browser, and the result is linkable.
  const [params, setParams] = useSearchParams();
  const submitted = params.get('q') ?? '';
  // In the URL too, so Back restores the whole search, not half of it.
  const scope = params.get('color_scope') ?? 'major';
  // The input is still local: it changes on every keystroke and the URL should
  // not.
  const [query, setQuery] = useState(submitted);

  const { data, isLoading, error } = useQuery({
    queryKey: ['guest-collection', submitted, scope],
    queryFn: () => getGuestCollection(submitted || undefined, scope),
    retry: false,
    // Serve the cached page instantly on Back. Without this the list is empty
    // for a beat while it refetches, and the browser — which restores scroll
    // against the height of the page as it is at that moment — puts you at the
    // top. Cached data means the page is its full height immediately and your
    // position survives.
    staleTime: 60_000,
  });

  if (error) {
    return (
      <div className="text-center py-5 text-secondary" style={{ paddingTop: '20vh' }}>
        <h1>HEADROOM</h1>
        <p>Guest browsing isn't available.</p>
        <Link to="/login" className="btn btn-outline-primary btn-sm">Sign in</Link>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: '1.5rem 1rem' }}>
      <div className="d-flex justify-content-between align-items-start gap-2 flex-wrap mb-1">
        <h1 className="mb-0">The collection</h1>
        <Link to="/login" className="btn btn-outline-secondary btn-sm">Sign in</Link>
      </div>
      <p className="text-secondary small mb-3">Browsing as a guest.</p>

      <form
        className="d-flex gap-2 mb-4"
        onSubmit={e => {
          e.preventDefault();
          const next = query.trim();
          // `replace` so a run of searches doesn't build a back stack you have
          // to unwind one press at a time to leave the page.
          setParams(
            next ? { q: next, ...(scope !== 'major' && { color_scope: scope }) } : {},
            { replace: true },
          );
        }}
      >
        <input
          aria-label="Search the collection"
          className="form-control"
          placeholder="Search by model, colour, style…"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        <button type="submit" className="btn btn-primary">Search</button>
        {submitted && (
          <button
            type="button"
            className="btn btn-outline-secondary"
            onClick={() => { setQuery(''); setParams({}, { replace: true }); }}
          >Clear</button>
        )}
      </form>

      {submitted && (
        <div className="mb-4">
          <ColorScopePicker
            value={scope}
            onChange={next => setParams(
              { q: submitted, ...(next !== 'major' && { color_scope: next }) },
              { replace: true },
            )}
          />
        </div>
      )}

      {isLoading || !data ? <LoadingSpinner /> : (
        <>
          <p className="text-secondary small mb-3">
            {data.hat_count} hat{data.hat_count !== 1 ? 's' : ''}
            {submitted && <> matching “{submitted}”</>}
          </p>
          <SharedCollectionGrid hats={data.hats} hrefFor={h => `/guest/hat/${h.id}`} />
        </>
      )}
    </div>
  );
}
