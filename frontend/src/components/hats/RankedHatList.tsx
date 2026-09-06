import type { ReactNode } from 'react';
import { Link } from 'react-router';
import type { HatRead } from '../../types';
import { tileSrc } from '../../lib/photo';

/**
 * A ranked "top N" list of hats — number, thumbnail, id, name, one figure.
 *
 * Stats and Valuation each carried a copy (`HatRank` / `HatList`) that had
 * already diverged in what a hat with no brand is called. One list, and the
 * empty state is a prop rather than something one page rendered inline and
 * the other forgot.
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
  if (!hats.length) {
    return typeof empty === 'string' ? <p className="text-muted small mb-0">{empty}</p> : <>{empty ?? null}</>;
  }
  return (
    <div>
      {hats.map((h, i) => (
        <Link
          key={h.id}
          to={`/hats/${h.id}`}
          className="hr-color-row text-decoration-none"
          style={{ paddingTop: '0.5rem' }}
        >
          {numbered && (
            <div className="font-mono fw-bold" style={{ color: 'var(--neon-purple)', minWidth: 22 }}>
              {i + 1}.
            </div>
          )}
          {h.photo_path ? (
            <img src={tileSrc(h)} alt="" className="hr-thumb flex-shrink-0" style={{ width: 40, height: 40 }} />
          ) : (
            <div className="rounded flex-shrink-0" style={{ width: 40, height: 40, background: 'rgba(0,0,0,0.3)' }} />
          )}
          <div className="flex-grow-1" style={{ minWidth: 0 }}>
            <div className="font-mono small" style={{ color: 'var(--neon-cyan)' }}>
              {h.display_id || `Hat #${h.id}`}
            </div>
            <div
              className="text-secondary small"
              style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
            >
              {h.brand || h.style.replace(/_/g, ' ')}{h.model_name && ` · ${h.model_name}`}
            </div>
          </div>
          {valueTone === 'accent' ? (
            <div className="font-mono fw-bold flex-shrink-0" style={{ color: 'var(--neon-pink)' }}>
              {valueFor(h)}
            </div>
          ) : (
            <div className="text-secondary small font-mono flex-shrink-0">{valueFor(h)}</div>
          )}
        </Link>
      ))}
    </div>
  );
}
