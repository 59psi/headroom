import { useMemo, useState } from 'react';
import type { MatchAgreement } from '../../types';

/**
 * The searchable, ranked list both link dialogs pick from — hats for a
 * purchase, purchases for a hat. Ranked by the server (what the matcher's
 * rules accept first, then resemblance), never filtered by it: the right
 * answer is sometimes one those rules exclude, which is why a person is
 * choosing at all. The search box narrows; it never reorders.
 */
export interface PickRow {
  id: number;
  title: string;
  detail: string;
  /** Said under the row when picking it also moves or replaces a link. */
  note?: string | null;
  /** A photo URL, `null` for an item with none; omit for rows that never have one. */
  thumb?: string | null;
  /** The matcher's own rules accept the pair. */
  fits: boolean;
  agrees: MatchAgreement[];
  /** The text the search box matches against. */
  search: string;
}

const AGREES: Record<MatchAgreement, string> = {
  model: 'Model', series: 'Series', colorway: 'Colorway', size: 'Size', price: 'Price',
};

/** Rows drawn before "Show all" — a full shelf is 250 hats on a phone. */
const SHOWN = 40;

export function PickList({ rows, label, onPick }: {
  rows: PickRow[];
  /** The search box's accessible name. */
  label: string;
  onPick: (id: number) => void;
}) {
  const [query, setQuery] = useState('');
  const [showAll, setShowAll] = useState(false);
  const matching = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    if (words.length === 0) return rows;
    return rows.filter(r => {
      const text = r.search.toLowerCase();
      return words.every(w => text.includes(w));
    });
  }, [rows, query]);
  const visible = showAll ? matching : matching.slice(0, SHOWN);

  return (
    <>
      <input
        type="search"
        className="form-control mb-2"
        aria-label={label}
        placeholder="Search…"
        value={query}
        onChange={e => setQuery(e.target.value)}
      />
      {matching.length === 0 && (
        <p className="text-secondary small mb-0">Nothing matches “{query}”.</p>
      )}
      <ul className="hr-pick-list">
        {visible.map(r => (
          <li key={r.id}>
            <button type="button" className="hr-pick-row" onClick={() => onPick(r.id)}>
              {r.thumb !== undefined && (
                r.thumb
                  ? <img className="hr-pick-thumb" src={r.thumb} alt="" loading="lazy" />
                  : <span className="hr-pick-thumb" aria-hidden="true" />
              )}
              <span className="hr-pick-text">
                <span className="hr-pick-title">{r.title}</span>
                <span className="hr-pick-detail">{r.detail}</span>
                {(r.fits || r.agrees.length > 0) && (
                  <span className="hr-pick-agrees">
                    {r.fits && <span className="hr-pick-chip is-fit">Fits</span>}
                    {r.agrees.map(a => <span key={a} className="hr-pick-chip">{AGREES[a]}</span>)}
                  </span>
                )}
                {r.note && <span className="hr-pick-note">{r.note}</span>}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {!showAll && matching.length > SHOWN && (
        <button type="button" className="btn btn-outline-secondary btn-sm mt-2" onClick={() => setShowAll(true)}>
          Show all {matching.length}
        </button>
      )}
    </>
  );
}

/**
 * The step after picking: what the link will do, and the one choice it needs
 * from you — whose colorway wins when the receipt and the hat disagree. The
 * hat's own colorway is kept unless you say otherwise; a link never
 * overwrites what a hat already says on its own.
 */
export function LinkConfirm({ thumb, heading, lines, warnings, colorway }: {
  thumb?: string | null;
  heading: string;
  lines: string[];
  warnings: string[];
  colorway?: { receipt: string; hat: string; checked: boolean; onChange: (next: boolean) => void };
}) {
  return (
    <div className="hr-pick-confirm">
      {thumb && <img className="hr-pick-confirm-photo" src={thumb} alt="" />}
      <div>
        <div className="hr-pick-title">{heading}</div>
        {lines.map(line => <div key={line} className="hr-pick-detail">{line}</div>)}
        {warnings.map(w => <p key={w} className="hr-pick-warn small mb-0 mt-2">{w}</p>)}
        {colorway && (
          <div className="form-check mt-2">
            <input
              id="link-receipt-colorway"
              type="checkbox"
              className="form-check-input"
              checked={colorway.checked}
              onChange={e => colorway.onChange(e.target.checked)}
            />
            <label className="form-check-label small" htmlFor="link-receipt-colorway">
              Use the receipt&rsquo;s colorway &ldquo;{colorway.receipt}&rdquo; instead of
              the hat&rsquo;s &ldquo;{colorway.hat}&rdquo;
            </label>
          </div>
        )}
      </div>
    </div>
  );
}
