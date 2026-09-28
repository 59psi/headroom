import { useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router';
import { getGuestCollection } from '../api/guest';
import { isNotFound } from '../api/client';
import { SharedCollectionGrid, SharedCollectionSkeleton } from '../components/share/SharedCollectionGrid';
import { PublicNotice, PublicPage } from '../components/share/PublicPage';
import { PublicLoadError } from '../components/share/PublicLoadError';
import { ColorScopePicker } from '../components/common/ColorScopePicker';
import { plural } from '../lib/format';
import { qk } from '../lib/queryKeys';

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

  const guestQ = useQuery({
    // Under `qk.guest.all()`, so a hat change refreshes what a guest sees
    // (`invalidateHatViews`) — the old `['guest-collection', …]` key was
    // under nothing.
    queryKey: qk.guest.collection(submitted, scope),
    queryFn: () => getGuestCollection(submitted || undefined, scope),
    retry: false,
    // Serve the cached page instantly on Back. Without this the list is empty
    // for a beat while it refetches, and the browser — which restores scroll
    // against the height of the page as it is at that moment — puts you at the
    // top. Cached data means the page is its full height immediately and your
    // position survives.
    staleTime: 60_000,
    // A new search keeps the last result on screen, dimmed, until the answer
    // lands. Each search is a new query key, so without this every submit
    // (and every color-scope tap) blanked the grid to a spinner and back —
    // the page visibly reloading for what is one field changing.
    placeholderData: keepPreviousData,
  });
  const { data, isLoading, isPlaceholderData, error } = guestQ;

  // Guest browsing switched off answers 404 — indistinguishable, on purpose,
  // from a path that does not exist. Anything else is the server failing,
  // and "isn't available" would be the wrong thing to tell a guest.
  if (error && !isNotFound(error)) {
    return <PublicPage><PublicLoadError query={guestQ} /></PublicPage>;
  }
  if (error) {
    return (
      <PublicPage>
        <PublicNotice
          title="Guest browsing isn't available"
          action={<Link to="/login" className="btn btn-primary">Sign in</Link>}
        />
      </PublicPage>
    );
  }

  const count = data?.hat_count ?? 0;

  return (
    <PublicPage action={<Link to="/login" className="btn btn-outline-secondary btn-sm">Sign in</Link>}>
      <div className="hr-public-head">
        <h1>The collection</h1>
        <p className="hr-public-sub">Browsing as a guest.</p>
      </div>

      <form
        className="hr-field-row hr-public-search"
        role="search"
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
        <div className="hr-search-field">
          <svg className="hr-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
            <circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" />
          </svg>
          <input
            aria-label="Search the collection"
            className="form-control"
            // The keyboard's return key reads "Search". Not `type="search"`:
            // WebKit adds its own × to those, which empties the box but
            // leaves the submitted search in place — a second, lesser Clear.
            enterKeyHint="search"
            placeholder="Search by model, color, style…"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
        </div>
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
        <div className="hr-public-scope">
          <ColorScopePicker
            value={scope}
            onChange={next => setParams(
              { q: submitted, ...(next !== 'major' && { color_scope: next }) },
              { replace: true },
            )}
          />
        </div>
      )}

      {isLoading || !data ? <SharedCollectionSkeleton /> : (
        <>
          {/* A live region, so a screen reader hears the new count when a
              search lands instead of having to go looking for it. */}
          <p className="hr-result-count" role="status">
            {isPlaceholderData ? 'Searching…' : (
              <>
                {plural(count, 'hat')}
                {submitted && <> matching “{submitted}”</>}
              </>
            )}
          </p>
          <div
            className={`hr-results${isPlaceholderData ? ' is-stale' : ''}`}
            aria-busy={isPlaceholderData || undefined}
          >
            <SharedCollectionGrid hats={data.hats} hrefFor={h => `/guest/hat/${h.id}`} />
          </div>
        </>
      )}
    </PublicPage>
  );
}
