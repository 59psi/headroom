import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { getGuestCollection } from '../api/guest';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { SharedCollectionGrid } from '../components/share/SharedCollectionGrid';

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
  const [query, setQuery] = useState('');
  // Only the submitted term hits the server — a request per keystroke is a lot
  // of load to hand an unauthenticated caller.
  const [submitted, setSubmitted] = useState('');

  const { data, isLoading, error } = useQuery({
    queryKey: ['guest-collection', submitted],
    queryFn: () => getGuestCollection(submitted || undefined),
    retry: false,
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
        onSubmit={e => { e.preventDefault(); setSubmitted(query.trim()); }}
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
            onClick={() => { setQuery(''); setSubmitted(''); }}
          >Clear</button>
        )}
      </form>

      {isLoading || !data ? <LoadingSpinner /> : (
        <>
          <p className="text-secondary small mb-3">
            {data.hat_count} hat{data.hat_count !== 1 ? 's' : ''}
            {submitted && <> matching “{submitted}”</>}
          </p>
          <SharedCollectionGrid hats={data.hats} />
        </>
      )}
    </div>
  );
}
