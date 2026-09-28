import { describeError } from '../common/ErrorNote';
import type { Retryable } from '../common/LoadError';
import { PublicNotice } from './PublicPage';

/**
 * A public page (a share link, guest browsing, a guest's hat) whose data did
 * not load for a reason OTHER than "it isn't there".
 *
 * Those pages told every failure the same story: a 500 or a dropped
 * connection read "This share link is invalid, expired, or was revoked" or
 * "Guest browsing isn't available" — telling the person holding a good link
 * that it had been taken away. Only a 404 means that; anything else is the
 * server not answering, which is said as such, with a retry in place.
 */
export function PublicLoadError({ query }: { query: Retryable }) {
  return (
    <PublicNotice
      title="Couldn’t load this right now"
      detail={<>Headroom didn&rsquo;t answer ({describeError(query.error)}). Nothing about the link has changed.</>}
      action={
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => { void query.refetch(); }}
          disabled={query.isFetching}
        >{query.isFetching ? 'Retrying…' : 'Try again'}</button>
      }
    />
  );
}
