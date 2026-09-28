import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { getStyles, getSizes, getConditions, getConstructions } from '../../api/hats';
import { getRoomOptions } from '../../api/rooms';
import type { ColorTag } from '../../types';

/** The subset of a hat the shared filters actually read — satisfied by both
 *  `HatRead` (Hats page) and `SearchResult` (Search page). */
export interface FilterableHat {
  style: string;
  size: string;
  condition: string;
  is_beanie: boolean;
  /** Free-form fabric/build ("HYDRO", "HYDROLite", "Thermal", "Piña"…), and
   *  frequently absent — analysis NEVER writes it (owner-only; see
   *  `_apply_construction`), so a blank means nobody has recorded it, which is
   *  why `(none)` is an askable filter value. */
  construction: string | null;
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
  /** A construction value, or `NO_CONSTRUCTION` for "not recorded". */
  construction: string;
}

/**
 * Sentinel for "no construction recorded".
 *
 * Worth a filter option of its own: the field is nullable by design, so
 * "which hats still need this filled in?" is a real question and there is
 * otherwise no way to ask it. Readable rather than an escape sequence because
 * it goes into the URL (`/hats?construction=(none)`). A fabric genuinely named
 * "(none)" would collide; that is not a material.
 */
export const NO_CONSTRUCTION = '(none)';

const EMPTY: HatFilterState = {
  style: '', size: '', condition: '', type: '', color: '', room: '', construction: '',
};

/**
 * Filter state plus the option lists the bar renders.
 *
 * `room` is held here because both pages show the Room select and count it as
 * an active filter, but it is deliberately NOT applied by `matchesHatFilters`:
 * the Hats page matches `room_id` client-side while Search passes the room to
 * the API and gets a pre-filtered list back.
 */
export function useHatFilters() {
  // Seeded from the URL so other pages can link INTO a filtered view — the
  // stats page's "23 A-Game" bar goes to /hats?style=a_game and the list is
  // already narrowed on arrival. Read once as the initial value rather than
  // synced continuously: after landing, the selects own the state, and a
  // two-way binding would fight the user every time they widened a filter the
  // link had set. (The page mirrors the state BACK into the URL with
  // `useMirrorToUrl` — one-way, state → URL — so Back and reload return to
  // the same view; that direction never overrides a choice.)
  const [searchParams] = useSearchParams();
  const [filters, setFilters] = useState<HatFilterState>(() => {
    const seeded = { ...EMPTY };
    for (const key of Object.keys(EMPTY) as Array<keyof HatFilterState>) {
      const value = searchParams.get(key);
      // A hex is a color SEARCH (`/search?color=%23aabbcc`, the form the stats
      // page's color bars used to link with), never a Color filter value —
      // those are palette names like "blue". Seeding it here set the filter
      // to "#aabbcc", which no hat's `general_color` can equal, so the ranked
      // results arrived and were all filtered away: "0 of 12 results".
      if (key === 'color' && value?.startsWith('#')) continue;
      if (value) seeded[key] = value;
    }
    return seeded;
  });
  // Starts closed even when a link arrived with filters applied. It used to
  // open so the reason the list is short was on screen; `ActiveFilterChips`
  // now shows exactly that in one line, and a removable chip is a shorter way
  // to widen the list than opening seven selects to find the one that is set.
  // Now that filters round-trip through the URL, opening the bar on arrival
  // would also have unfolded it every time you came Back from a hat.
  const [isOpen, setIsOpen] = useState(false);

  const styles = useQuery({ queryKey: ['meta', 'styles'], queryFn: getStyles });
  const sizes = useQuery({ queryKey: ['meta', 'sizes'], queryFn: getSizes });
  const conditions = useQuery({ queryKey: ['meta', 'conditions'], queryFn: getConditions });
  const rooms = useQuery({ queryKey: ['meta', 'rooms'], queryFn: getRoomOptions });
  // Curated list merged with everything actually in use, so a specialty fabric
  // typed once is filterable from then on without shipping a migration.
  const constructions = useQuery({ queryKey: ['meta', 'constructions'], queryFn: getConstructions });

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
    options: { styles, sizes, conditions, rooms, constructions },
  };
}

/**
 * Mirror page state into the query string, replacing the current history
 * entry rather than pushing one per change.
 *
 * Filters and searches lived only in component state, so opening a hat and
 * pressing Back remounted the list with every filter gone and the search box
 * empty — the list you were halfway through had to be rebuilt from scratch.
 * With the state in the URL, Back lands on `/hats?style=a_game` and
 * `useHatFilters` seeds from it as it always has for inbound links.
 *
 * `replace`, never `push`: a history entry per keystroke would make Back walk
 * through every intermediate search instead of leaving the page.
 *
 * Only the keys passed are touched — the Search page's `q` and the shared
 * filter keys coexist in one query string — and an empty value removes its
 * key, so an unfiltered list keeps a clean `/hats`. One call per page: two
 * writers would each rebuild the query string from the same stale snapshot
 * and the second would undo the first.
 */
export function useMirrorToUrl(values: Record<string, string>) {
  const [params, setParams] = useSearchParams();
  // Serialized so the effect keys on the VALUES, not on the object identity a
  // caller rebuilds every render.
  const serialized = JSON.stringify(values);
  useEffect(() => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(JSON.parse(serialized) as Record<string, string>)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    if (next.toString() !== params.toString()) setParams(next, { replace: true });
  }, [serialized, params, setParams]);
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
  if (f.construction) {
    const value = hat.construction?.trim() ?? '';
    if (f.construction === NO_CONSTRUCTION) {
      if (value) return false;
    } else if (value.toLowerCase() !== f.construction.toLowerCase()) {
      // Full equality, never substring: "HYDRO" must not match "HYDROLite".
      // Case-insensitive only to tolerate rows written before the vocabulary
      // service began snapping values to one spelling on write.
      return false;
    }
  }
  return true;
}

type FilterState = ReturnType<typeof useHatFilters>;

interface FilterBarProps {
  state: FilterState;
  /** Colors present in the current result set. */
  colors: string[];
  /** Total active count including page-specific extras. Defaults to the shared seven. */
  activeCount?: number;
  /** Reset page-specific extras; runs alongside clearing the shared filters. */
  onClearExtras?: () => void;
  /** Page-specific extra selects (e.g. Brand on the Hats page). Wrap each in
   *  `.hr-cp-field` so it takes one cell of the grid. */
  children?: React.ReactNode;
}

/**
 * The seven shared filter selects, plus any page-specific extras as children.
 *
 * Every select applies on change — there is no Apply button, and the list
 * under the bar re-filters as you choose.
 */
export function HatFilterBar({ state, colors, activeCount, onClearExtras, children }: FilterBarProps) {
  const { filters, set, clear, options } = state;
  const shownCount = activeCount ?? state.activeCount;
  return (
    <div className="card hr-cp-filters mb-3" role="group" aria-label="Filters">
      <div className="card-body">
        <div className="hr-cp-filter-grid">
          <div className="hr-cp-field">
            <label className="form-label">Style</label>
            <select aria-label="Style" className="form-select form-select-sm" value={filters.style} onChange={e => set('style', e.target.value)}>
              <option value="">All</option>
              {options.styles.data?.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div className="hr-cp-field">
            <label className="form-label">Size</label>
            <select aria-label="Size" className="form-select form-select-sm" value={filters.size} onChange={e => set('size', e.target.value)}>
              <option value="">All</option>
              {options.sizes.data?.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div className="hr-cp-field">
            <label className="form-label">Condition</label>
            <select aria-label="Condition" className="form-select form-select-sm" value={filters.condition} onChange={e => set('condition', e.target.value)}>
              <option value="">All</option>
              {options.conditions.data?.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </div>
          <div className="hr-cp-field">
            <label className="form-label">Type</label>
            <select aria-label="Type" className="form-select form-select-sm" value={filters.type} onChange={e => set('type', e.target.value)}>
              <option value="">All</option>
              <option value="regular">Regular</option>
              <option value="beanie">Beanies</option>
            </select>
          </div>
          <div className="hr-cp-field">
            <label className="form-label">Color</label>
            <select aria-label="Color" className="form-select form-select-sm" value={filters.color} onChange={e => set('color', e.target.value)}>
              <option value="">All</option>
              {colors.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div className="hr-cp-field">
            <label className="form-label">Room</label>
            <select aria-label="Room" className="form-select form-select-sm" value={filters.room} onChange={e => set('room', e.target.value)}>
              <option value="">All</option>
              {options.rooms.data?.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </div>
          <div className="hr-cp-field">
            <label className="form-label">Construction</label>
            <select aria-label="Construction" className="form-select form-select-sm" value={filters.construction} onChange={e => set('construction', e.target.value)}>
              <option value="">All</option>
              {options.constructions.data?.map(c => <option key={c} value={c}>{c}</option>)}
              <option value={NO_CONSTRUCTION}>Not recorded</option>
            </select>
          </div>
          {children}
        </div>
        {shownCount > 0 && (
          <div className="hr-cp-filter-foot">
            <span>{shownCount} active</span>
            <button
              type="button"
              className="btn btn-link btn-sm hr-cp-clear"
              onClick={() => { clear(); onClearExtras?.(); }}
            >Clear filters</button>
          </div>
        )}
      </div>
    </div>
  );
}

/** A page-specific filter (Brand on the Hats page) shown as a chip. */
export interface ExtraFilterChip {
  key: string;
  /** "Brand: melin" */
  label: string;
  onRemove: () => void;
}

/** "A-Game" for `a_game`, from the option list when it has loaded. */
function optionLabel(opts: ReadonlyArray<{ value: string | number; label: string }> | undefined, value: string): string {
  return opts?.find(o => String(o.value) === value)?.label ?? value.replace(/_/g, ' ');
}

/**
 * What is filtering the list, one removable chip per filter — shown while the
 * filter bar is folded away.
 *
 * Without it a filtered list looked exactly like a small collection: the only
 * sign was a digit on the Filters button, and undoing one filter meant opening
 * the bar and finding which of seven selects was set.
 */
export function ActiveFilterChips({ state, extras = [], onClearExtras }: {
  state: FilterState;
  extras?: ExtraFilterChip[];
  /** Reset page-specific extras when "Clear all" is used. */
  onClearExtras?: () => void;
}) {
  const { filters, set, clear, options } = state;
  const chips: ExtraFilterChip[] = [];
  const add = (key: keyof HatFilterState, name: string, text: string) => {
    chips.push({ key, label: `${name}: ${text}`, onRemove: () => set(key, '') });
  };
  if (filters.style) add('style', 'Style', optionLabel(options.styles.data, filters.style));
  if (filters.size) add('size', 'Size', optionLabel(options.sizes.data, filters.size));
  if (filters.condition) add('condition', 'Condition', optionLabel(options.conditions.data, filters.condition));
  if (filters.type) add('type', 'Type', filters.type === 'beanie' ? 'Beanies' : 'Regular');
  if (filters.color) add('color', 'Color', filters.color);
  if (filters.room) add('room', 'Room', optionLabel(options.rooms.data, filters.room));
  if (filters.construction) {
    add('construction', 'Construction', filters.construction === NO_CONSTRUCTION ? 'Not recorded' : filters.construction);
  }
  chips.push(...extras);
  if (!chips.length) return null;

  return (
    <div className="hr-cp-chips mb-3" role="group" aria-label="Active filters">
      {chips.map(c => (
        <button
          key={c.key}
          type="button"
          className="hr-cp-chip is-active is-removable"
          aria-label={`Remove filter ${c.label}`}
          onClick={c.onRemove}
        >
          {c.label}
          <span className="hr-cp-chip-x" aria-hidden="true">×</span>
        </button>
      ))}
      {chips.length > 1 && (
        <button
          type="button"
          className="btn btn-link btn-sm hr-cp-clear"
          onClick={() => { clear(); onClearExtras?.(); }}
        >Clear all</button>
      )}
    </div>
  );
}

/** The Filters toggle button + count badge, shared by both pages. */
export function FilterToggleButton({ activeCount, isOpen, onToggle }: {
  activeCount: number; isOpen: boolean; onToggle: (open: boolean) => void;
}) {
  // Neutral even when filters are set: the active state is the tint and the
  // count, not a second gradient button beside the page's one primary action.
  return (
    <button
      type="button"
      className={`btn btn-sm btn-outline-secondary hr-cp-filter-toggle${activeCount ? ' is-active' : ''}`}
      onClick={() => onToggle(!isOpen)}
      aria-expanded={isOpen}
    >
      <svg className="hr-cp-icon" width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M2 3h12M4.5 8h7M7 13h2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
      Filters
      {activeCount > 0 && (
        <span className="hr-cp-count-badge">
          {activeCount}<span className="visually-hidden"> active</span>
        </span>
      )}
    </button>
  );
}

export { EMPTY as EMPTY_HAT_FILTERS };
