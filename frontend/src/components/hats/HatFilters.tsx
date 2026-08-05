import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getStyles, getSizes, getConditions } from '../../api/hats';
import { getRoomOptions } from '../../api/rooms';
import type { ColorTag } from '../../types';

/** The subset of a hat the shared filters actually read — satisfied by both
 *  `HatRead` (Hats page) and `SearchResult` (Search page). */
export interface FilterableHat {
  style: string;
  size: string;
  condition: string;
  is_beanie: boolean;
  colors: ColorTag[];
}

export interface HatFilterState {
  style: string;
  size: string;
  condition: string;
  /** '' | 'regular' | 'beanie' */
  type: string;
  color: string;
  room: string;
}

const EMPTY: HatFilterState = { style: '', size: '', condition: '', type: '', color: '', room: '' };

/**
 * Filter state plus the option lists the bar renders.
 *
 * `room` is held here because both pages show the Room select and count it as
 * an active filter, but it is deliberately NOT applied by `matchesHatFilters`:
 * the Hats page matches `room_id` client-side while Search passes the room to
 * the API and gets a pre-filtered list back.
 */
export function useHatFilters() {
  const [filters, setFilters] = useState<HatFilterState>(EMPTY);
  const [isOpen, setIsOpen] = useState(false);

  const styles = useQuery({ queryKey: ['meta', 'styles'], queryFn: getStyles });
  const sizes = useQuery({ queryKey: ['meta', 'sizes'], queryFn: getSizes });
  const conditions = useQuery({ queryKey: ['meta', 'conditions'], queryFn: getConditions });
  const rooms = useQuery({ queryKey: ['meta', 'rooms'], queryFn: getRoomOptions });

  const activeCount = Object.values(filters).filter(Boolean).length;

  function set<K extends keyof HatFilterState>(key: K, value: HatFilterState[K]) {
    setFilters(prev => ({ ...prev, [key]: value }));
  }

  return {
    filters,
    set,
    clear: () => setFilters(EMPTY),
    activeCount,
    isOpen,
    setIsOpen,
    options: { styles, sizes, conditions, rooms },
  };
}

/** Distinct `general_color` values across a result set, sorted — the Color select's options. */
export function collectGeneralColors(hats: readonly FilterableHat[] | undefined): string[] {
  if (!hats) return [];
  const colors = new Set<string>();
  hats.forEach(h => h.colors.forEach(c => {
    if (c.general_color) colors.add(c.general_color);
  }));
  return [...colors].sort();
}

/** The predicates both pages apply identically. Room/brand/assignment are the
 *  caller's job — they differ per page (see `useHatFilters`). */
export function matchesHatFilters(hat: FilterableHat, f: HatFilterState): boolean {
  if (f.style && hat.style !== f.style) return false;
  if (f.size && hat.size !== f.size) return false;
  if (f.condition && hat.condition !== f.condition) return false;
  if (f.type === 'beanie' && !hat.is_beanie) return false;
  if (f.type === 'regular' && hat.is_beanie) return false;
  if (f.color && !hat.colors.some(c => c.general_color === f.color)) return false;
  return true;
}

interface FilterBarProps {
  state: ReturnType<typeof useHatFilters>;
  /** Colors present in the current result set. */
  colors: string[];
  /** Total active count including page-specific extras. Defaults to the shared six. */
  activeCount?: number;
  /** Reset page-specific extras; runs alongside clearing the shared filters. */
  onClearExtras?: () => void;
  /** Page-specific extra selects (e.g. Brand on the Hats page). */
  children?: React.ReactNode;
}

/** The six shared filter selects, plus any page-specific extras as children. */
export function HatFilterBar({ state, colors, activeCount, onClearExtras, children }: FilterBarProps) {
  const { filters, set, clear, options } = state;
  const shownCount = activeCount ?? state.activeCount;
  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="row g-2">
          <div className="col-6 col-md-3">
            <label className="form-label">Style</label>
            <select aria-label="Style" className="form-select form-select-sm" value={filters.style} onChange={e => set('style', e.target.value)}>
              <option value="">All</option>
              {options.styles.data?.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div className="col-6 col-md-3">
            <label className="form-label">Size</label>
            <select aria-label="Size" className="form-select form-select-sm" value={filters.size} onChange={e => set('size', e.target.value)}>
              <option value="">All</option>
              {options.sizes.data?.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div className="col-6 col-md-3">
            <label className="form-label">Condition</label>
            <select aria-label="Condition" className="form-select form-select-sm" value={filters.condition} onChange={e => set('condition', e.target.value)}>
              <option value="">All</option>
              {options.conditions.data?.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </div>
          <div className="col-6 col-md-3">
            <label className="form-label">Type</label>
            <select aria-label="Type" className="form-select form-select-sm" value={filters.type} onChange={e => set('type', e.target.value)}>
              <option value="">All</option>
              <option value="regular">Regular</option>
              <option value="beanie">Beanies</option>
            </select>
          </div>
          <div className="col-6 col-md-3">
            <label className="form-label">Color</label>
            <select aria-label="Color" className="form-select form-select-sm" value={filters.color} onChange={e => set('color', e.target.value)}>
              <option value="">All</option>
              {colors.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div className="col-6 col-md-3">
            <label className="form-label">Room</label>
            <select aria-label="Room" className="form-select form-select-sm" value={filters.room} onChange={e => set('room', e.target.value)}>
              <option value="">All</option>
              {options.rooms.data?.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </div>
          {children}
        </div>
        {shownCount > 0 && (
          <button
            type="button"
            className="btn btn-link btn-sm mt-2 p-0"
            style={{ color: 'var(--neon-red)' }}
            onClick={() => { clear(); onClearExtras?.(); }}
          >Clear filters</button>
        )}
      </div>
    </div>
  );
}

/** The Filters toggle button + count badge, shared by both pages. */
export function FilterToggleButton({ activeCount, isOpen, onToggle }: {
  activeCount: number; isOpen: boolean; onToggle: (open: boolean) => void;
}) {
  return (
    <button
      type="button"
      className={`btn btn-sm ${activeCount ? 'btn-primary' : 'btn-outline-secondary'}`}
      onClick={() => onToggle(!isOpen)}
    >
      Filters{activeCount > 0 && <span className="badge bg-white ms-1">{activeCount}</span>}
    </button>
  );
}

export { EMPTY as EMPTY_HAT_FILTERS };
