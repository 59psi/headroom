import type { ReactNode } from 'react';
import { Link } from 'react-router';
import type { HatRead } from '../../types';
import { tileSrc } from '../../lib/photo';
import { useHatLabels } from '../../lib/labels';
import { hatName } from '../../lib/placement';

/**
 * A ranked "top N" list of hats — number, thumbnail, id, name, one figure.
 *
 * Stats and Valuation each carried a copy (`HatRank` / `HatList`) that had
 * already diverged in what a hat with no brand is called. One list, and the
 * empty state is a prop rather than something one page rendered inline and
 * the other forgot.
 *
 * An ordered list (`<ol>`) when it is a leaderboard, so the rows are one list
 * to a screen reader rather than ten loose links.
 *
 * The rank itself stays in the link's text, NOT aria-hidden in favor of the
 * list's own numbering: the list is `list-style: none` (the number is drawn
 * by us, in purple), and a list without a marker has no numbering to announce
 * — hiding the digit as well left "Most valuable" read out as ten hats in no
 * stated order. It is also part of what the link says: "3. A-001-02 …".
 */
export function RankedHatList({
  hats,
  valueFor,
  empty,
  numbered = true,
  valueTone = 'accent',
}: {
  hats: HatRead[];
  valueFor: (h: HatRead) => string;
  /** Rendered instead of the list when there is nothing to rank. */
  empty?: ReactNode;
  /** Drop the "1." rank column — for a list that is ordered but not a leaderboard. */
  numbered?: boolean;
  /** `accent` for a figure worth reading (a price), `muted` for a date or a note. */
  valueTone?: 'accent' | 'muted';
}) {
  // Above the early return: a hook must run on every render.
  const labels = useHatLabels();
  if (!hats.length) {
    return typeof empty === 'string' ? <p className="text-muted small mb-0">{empty}</p> : <>{empty ?? null}</>;
  }
  const List = numbered ? 'ol' : 'ul';
  return (
    <List className="hr-cp-rank-list">
      {hats.map((h, i) => (
        <li key={h.id}>
          <Link to={`/hats/${h.id}`} className="hr-cp-rank">
            {numbered && (
              <span className="hr-cp-rank-num">
                {i + 1}<span className="visually-hidden">.</span>
              </span>
            )}
            {h.photo_path ? (
              <img src={tileSrc(h)} alt="" className="hr-thumb hr-cp-rank-thumb" />
            ) : (
              <span className="hr-cp-rank-thumb hr-cp-thumb-empty" aria-hidden="true" />
            )}
            <span className="hr-cp-rank-main">
              {/* The id line only — the model has its own line below, so the
                  shelf id or "Hat #id", never the model twice. */}
              <span className="hr-cp-rank-id">{hatName({ id: h.id, display_id: h.display_id })}</span>
              <span className="hr-cp-rank-name">
                {h.brand || labels.style(h.style)}{h.model_name && ` · ${h.model_name}`}
              </span>
            </span>
            <span className={`hr-cp-rank-value${valueTone === 'muted' ? ' is-muted' : ''}`}>
              {valueFor(h)}
            </span>
          </Link>
        </li>
      ))}
    </List>
  );
}
