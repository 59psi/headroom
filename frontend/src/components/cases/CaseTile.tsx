import { Link } from 'react-router';
import type { CaseRead } from '../../types';
import { CaseCollage } from './CaseCollage';

/** "Empty", "4 beanies" or "3 hats" — a case holds one kind, so one count. */
export function caseOccupancyLabel(c: CaseRead): string {
  if (c.hat_count === 0) return 'Empty';
  if (c.beanie_count > 0) return `${c.beanie_count} beanie${c.beanie_count !== 1 ? 's' : ''}`;
  return `${c.regular_count} hat${c.regular_count !== 1 ? 's' : ''}`;
}

/**
 * Full and overfull are different states and the grid is where you'd notice
 * either. A bare count can't say which: "4 hats" looks identical whether the
 * case holds four comfortably or has one crammed in.
 *
 * Asked of the type the case actually HOLDS. Cases are type-exclusive, so the
 * unused type's `free_*` sits at its full nominal figure forever —
 * `free_regular + free_beanie === 0` therefore could never be true for a case
 * with regular hats in it (a full 3-hat case publishes `free_regular: 0,
 * free_beanie: 6`), and the badge only ever appeared on beanie cases.
 */
export function caseFillLabel(c: CaseRead): 'full' | 'overfull' | null {
  if (c.overfull) return 'overfull';
  const isFull = c.beanie_count > 0 ? c.free_beanie === 0 : c.free_regular === 0;
  return c.hat_count > 0 && isFull ? 'full' : null;
}

/** "Archive" / "Daily wear" — the two case types, in words. */
export function caseTypeLabel(c: Pick<CaseRead, 'case_type'>): string {
  return c.case_type === 'archive' ? 'Archive' : 'Daily wear';
}

/**
 * How full a case is, as a bar.
 *
 * Measured against `nominal_capacity` — the count at which the server says
 * the case reads as FULL, already per-case-override aware and already
 * switched to the beanie figure for a beanie case — so the bar can never
 * disagree with the Full/Overfull flag beside it. Nothing here restates a
 * capacity rule. Decorative: the words next to it ("3 hats", "Full") carry
 * the same facts for anyone not looking at a bar.
 */
export function CaseFillMeter({ c }: { c: CaseRead }) {
  const held = c.beanie_count > 0 ? c.beanie_count : c.regular_count;
  const pct = c.nominal_capacity > 0 ? Math.min(100, (held / c.nominal_capacity) * 100) : 0;
  const fill = caseFillLabel(c);
  return (
    <span className={`hr-case-meter${fill ? ` is-${fill}` : ''}`} aria-hidden="true">
      <span style={{ width: `${pct}%` }} />
    </span>
  );
}

/**
 * One case in a grid: the collage of what's inside, its id, its count.
 *
 * The Cases tab and the room page each carried their own copy, and the room's
 * had already lost the full/overfull tag. `showRoom` is off inside a room —
 * every tile would name the room you are standing in.
 */
export function CaseTile({ c, showRoom = true }: { c: CaseRead; showRoom?: boolean }) {
  const fillLabel = caseFillLabel(c);
  return (
    <Link to={`/cases/${c.display_id}`} className="card hr-case-tile text-decoration-none h-100">
      <div className="hr-case-tile-media">
        <CaseCollage thumbs={c.hat_thumbs} label={c.display_id} />
        {fillLabel && (
          <span className={`hr-case-flag is-${fillLabel}`}>
            {fillLabel === 'overfull' ? 'Overfull' : 'Full'}
          </span>
        )}
      </div>
      <div className="hr-case-tile-body">
        <div className="hr-case-tile-row">
          <span className="hr-case-tile-id">{c.display_id}</span>
          <span className="hr-case-tile-count">{caseOccupancyLabel(c)}</span>
        </div>
        <CaseFillMeter c={c} />
        <div className="hr-case-tile-meta">
          {caseTypeLabel(c)}{showRoom && <> · {c.room_name}</>}
        </div>
      </div>
    </Link>
  );
}

/**
 * Placeholder tiles in the shape of the grid, while the cases load.
 *
 * One "Loading cases…" status for the whole grid — six announcements for six
 * gray boxes would be noise — and the boxes themselves are decoration.
 * `label` names what is actually loading: the room page borrows this grid
 * while it fetches the ROOM, and "Loading cases…" there was only half true.
 */
export function CaseGridSkeleton({ count = 6, label = 'Loading cases…' }: { count?: number; label?: string }) {
  return (
    <div className="hr-case-grid">
      <span className="visually-hidden" role="status">{label}</span>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="card hr-case-tile hr-case-skel" aria-hidden="true">
          <span className="hr-skeleton hr-case-skel-media" />
          <div className="hr-case-tile-body">
            <span className="hr-skeleton hr-skeleton-line" />
            <span className="hr-skeleton hr-skeleton-line hr-case-skel-short" />
          </div>
        </div>
      ))}
    </div>
  );
}
