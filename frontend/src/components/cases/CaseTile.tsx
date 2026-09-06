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

/**
 * One case in a grid: the collage of what's inside, its id, its count.
 *
 * The Cases tab and the room page each carried their own copy, and the room's
 * had already lost the full/overfull tag. `showRoom` is off inside a room —
 * every tile would name the room you are standing in.
 */
export function CaseTile({ c, showRoom = true }: { c: CaseRead; showRoom?: boolean }) {
  const typeLabel = c.case_type === 'archive' ? 'Archive' : 'Daily Wear';
  const fillLabel = caseFillLabel(c);
  return (
    <Link to={`/cases/${c.display_id}`} className="card text-decoration-none h-100">
      <CaseCollage thumbs={c.hat_thumbs} label={c.display_id} />
      <div className="card-body d-flex justify-content-between align-items-center gap-2">
        <div>
          <div className="font-mono fw-bold fs-5" style={{ color: 'var(--neon-cyan)' }}>{c.display_id}</div>
          <div className="text-secondary small">{typeLabel}{showRoom && <> · {c.room_name}</>}</div>
        </div>
        <div className="text-end">
          <div className="font-mono fw-semibold" style={{ color: 'var(--neon-pink)' }}>{caseOccupancyLabel(c)}</div>
          {fillLabel && (
            <div className={`hr-fill-tag${c.overfull ? ' is-overfull' : ''}`}>{fillLabel}</div>
          )}
        </div>
      </div>
    </Link>
  );
}
