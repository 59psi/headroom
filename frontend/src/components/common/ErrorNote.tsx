/**
 * The one place a failed query or mutation is turned into words on the page.
 *
 * Every card and page used to decide for itself whether to say anything when
 * a request failed, and most decided not to: a `useMutation` with no
 * `onError` and no rendered `error` swallows the rejection — the button
 * un-presses and nothing is said — and a `useQuery` whose `error` is never
 * read renders its empty state, so a failed fetch looks exactly like "nothing
 * here". The guest-view switch reported OFF when its fetch failed; the
 * share-links card said "No active share links" while links were live;
 * "Unlink all" and "Clear them" failed without a word. Seventeen mutations
 * and some sixty queries were in that state, in seventeen spellings of the
 * same alert markup at the sites that did say something.
 *
 * Both TanStack results carry `isError`/`error`, so one component covers
 * both, and it takes a list because a card usually owns several: the first
 * that failed is what gets shown.
 */
import type { ReactNode } from 'react';

type Failing = { isError: boolean; error: unknown };

export function describeError(err: unknown): string {
  // `apiFetch` throws `Error` with a readable message already built by
  // `errorMessage()`; `String(err)` on that would prefix it with "Error: ".
  if (err instanceof Error) return err.message;
  return String(err);
}

export function ErrorNote({
  of,
  what,
  className = 'mt-2',
}: {
  of: Failing | Failing[];
  what?: ReactNode;
  className?: string;
}) {
  const failed = (Array.isArray(of) ? of : [of]).find(x => x.isError);
  if (!failed) return null;
  return (
    <div className={`alert alert-danger small mb-0 hr-error-note ${className}`} role="alert">
      {/* An icon, not a glyph in the text: the message is what gets read
          out and what a test (or a bug report) quotes, so nothing decorative
          goes into its text content. */}
      <svg className="hr-error-note-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7.5v5.5" />
        <path d="M12 16.5h.01" />
      </svg>
      <span className="hr-error-note-msg">
        {what ? <><strong>{what}</strong> — </> : null}
        {describeError(failed.error)}
      </span>
    </div>
  );
}
