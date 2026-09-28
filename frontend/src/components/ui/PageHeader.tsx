import type { ReactNode } from 'react';
import { Link } from 'react-router';

/**
 * The top of a page: where you are, how much is here, and what you can do.
 *
 *   ‹ Back link                      (optional; "up" — the list this is in)
 *   PAGE TITLE  count ·········· status · actions
 *   One-line summary                 (optional)
 *
 * Ten areas were migrated in parallel, and the page head came out of it
 * hand-rolled five times: one for the case and room pages, one for the
 * collection pages, one each for the hat page, the Edit-hat form and Bulk
 * import. Same idea, five ideas of the gap, the bottom margin, where the
 * actions sit against a two-line title, and when they give up and wrap —
 * so Edit case put its "back to the case" link above the title while Edit hat
 * put the same link beside it, and a case id and a hat id were each set in
 * mono cyan by their own rule. This is the one.
 *
 * Layout, in one sentence: the title block on the left, the aside (status,
 * then actions) on the right, and on a phone the aside drops under the title
 * block rather than squeezing it. Where exactly it drops is chosen so that
 * every page that used to fit on one line at 390px still does, and every
 * page that used to wrap still wraps — see `.hr-page-head` in ui.css.
 *
 * The h1 keeps the display face the global `h1` rule gives it. `code` swaps
 * in mono for a title that IS an identifier (a case or hat id): the display
 * face reads "A-001" as "A-OO1", and the id is the one thing the page is
 * about, so it takes the head's one accent.
 *
 * `loading` holds the h1's place with a bar the h1's own height while the
 * page's subject (a room's name, a hat's id) is on its way, so the head does
 * not jump when it arrives. The bar is decoration only: the page's body
 * skeleton is its one "Loading…" announcement, as everywhere else.
 */
interface PageHeaderBase {
  /** "Up": the list or record this page is a child of. A quiet link with a
   *  chevron above the title — not a button, because it is navigation the
   *  browser's own Back usually does too. */
  back?: {
    to: string;
    /** The name of where it goes ("Cases", "A-001"). */
    label: ReactNode;
    /** Tooltip with the longer story ("…without saving"). */
    title?: string;
  };
  /** Set the title as an identifier: mono, cyan. */
  code?: boolean;
  /** A readout beside the title — how many things the page lists ("128",
   *  "12 of 128" while filtered). A live region: the number changes under
   *  the reader's hands as filters change, and hearing it is how a screen
   *  reader user learns the filter took. Put the noun in a visually hidden
   *  span so it is heard, not shown ("12 of 128 hats"). */
  count?: ReactNode;
  /** One line under the title: what the page holds, and small status pills
   *  about the page's subject ("Daily wear · Den", "Full"). */
  summary?: ReactNode;
  /** Status of the page's subject at the right, before the actions (the hat
   *  page's construction, analysis and condition badges) — where `Panel`
   *  puts a card's status. */
  status?: ReactNode;
  /** The page's own actions. Right-aligned on a wide screen; wrap under the
   *  title block on a phone. */
  actions?: ReactNode;
}

export type PageHeaderProps = PageHeaderBase & (
  | { title: ReactNode; loading?: false }
  | { title?: undefined; loading: true }
);

/** Rendered only when there is something to render: a `cond && …` that did
 *  not match passes `false`, and an empty count string `''`. */
function present(node: ReactNode): boolean {
  return node !== undefined && node !== null && node !== false && node !== '';
}

export function PageHeader(props: PageHeaderProps) {
  const { back, code = false, count, summary, status, actions } = props;
  const hasSummary = present(summary);
  const hasAside = present(status) || present(actions);
  // Stacked: the title block is more than the h1 alone, so the aside sits on
  // its last line (the summary, or the h1 under a back link) rather than
  // floating between two lines. A bare title centers it instead: on a touch
  // screen the 44px buttons would otherwise leave the title sitting low.
  const stacked = !!back || hasSummary;
  return (
    <header
      className={`hr-page-head${stacked ? ' is-stacked' : ''}${hasSummary ? ' has-summary' : ''}`}
    >
      <div className="hr-page-head-main">
        {back && (
          <Link to={back.to} className="hr-page-head-back" title={back.title}>
            {back.label}
          </Link>
        )}
        {props.loading ? (
          // `h1` class, not element: the bar takes the page title's exact
          // line height at every breakpoint (the non-breaking space gives it
          // a line), without being announced as an empty heading.
          <div className="h1 hr-skeleton hr-page-head-skel" aria-hidden="true">&nbsp;</div>
        ) : (
          <div className="hr-page-head-title">
            <h1 className={code ? 'hr-page-head-code' : undefined}>{props.title}</h1>
            {present(count) && (
              <span className="hr-page-head-count" aria-live="polite">{count}</span>
            )}
          </div>
        )}
        {hasSummary && <p className="hr-page-head-summary">{summary}</p>}
      </div>
      {hasAside && (
        <div className="hr-page-head-aside">
          {status}
          {actions}
        </div>
      )}
    </header>
  );
}
