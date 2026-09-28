import { useEffect, useId, useState } from 'react';
import { useSearchParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { getStyles, getSizes, getConditions, getConstructions } from '../../api/hats';
import { optionLabel } from '../../lib/labels';
import { qk } from '../../lib/queryKeys';
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

/** The Type filter: all, regular hats, or beanies. */
export type HatTypeFilter = '' | 'regular' | 'beanie';

export interface HatFilterState {
  style: string;
  size: string;
  condition: string;
  type: HatTypeFilter;
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

type Option = { value: string; label: string };

const TYPE_OPTIONS: readonly Option[] = [
  { value: 'regular', label: 'Regular' },
  { value: 'beanie', label: 'Beanies' },
];

function isTypeFilter(v: string): v is HatTypeFilter {
  return v === '' || TYPE_OPTIONS.some(o => o.value === v);
}

/** The option lists `useHatFilters` loads, as `FILTER_FIELDS` reads them. */
type FilterOptions = ReturnType<typeof useHatFilters>['options'];

/**
 * Every shared filter, once: its label, its choices, whether a URL value may
 * seed it, and how a hat passes it.
 *
 * The filter set used to be spelled out five times — the state type, its
 * empty value, a hand-written `<select>` block per filter in the bar, a line
 * per filter in the chips and a predicate in `matchesHatFilters` — and the
 * Type filter's words were typed twice. Adding a filter was five edits, and
 * the one missed showed up as a chip that said "beanie" beside a select that
 * said "Beanies". Now it is a row here.
 */
interface FilterField {
  key: keyof HatFilterState;
  label: string;
  /** The choices after "All". `colors` is what the current result set holds. */
  options: (o: FilterOptions, colors: readonly string[]) => readonly Option[];
  /** Whether a value from the URL may seed this filter. Default: any. */
  accepts?: (raw: string) => boolean;
  /** Whether `hat` passes a set filter. Absent = the PAGE applies it (see
   *  `useHatFilters` on Room). */
  matches?: (hat: FilterableHat, value: string) => boolean;
}

const FILTER_FIELDS: readonly FilterField[] = [
  {
    key: 'style', label: 'Style',
    options: o => o.styles.data ?? [],
    matches: (h, v) => h.style === v,
  },
  {
    key: 'size', label: 'Size',
    options: o => o.sizes.data ?? [],
    matches: (h, v) => h.size === v,
  },
  {
    key: 'condition', label: 'Condition',
    options: o => o.conditions.data ?? [],
    matches: (h, v) => h.condition === v,
  },
  {
    key: 'type', label: 'Type',
    options: () => TYPE_OPTIONS,
    accepts: isTypeFilter,
    matches: (h, v) => (v === 'beanie' ? h.is_beanie : !h.is_beanie),
  },
  {
    key: 'color', label: 'Color',
    options: (_o, colors) => colors.map(c => ({ value: c, label: c })),
    // A hex is a color SEARCH (`/search?color=%23aabbcc`, the form the stats
    // page's color bars used to link with), never a Color filter value —
    // those are palette names like "blue". Seeding it here set the filter to
    // "#aabbcc", which no hat's `general_color` can equal, so the ranked
    // results arrived and were all filtered away: "0 of 12 results".
    accepts: raw => !raw.startsWith('#'),
    matches: (h, v) => h.colors.some(c => c.general_color === v),
  },
  {
    key: 'room', label: 'Room',
    options: o => (o.rooms.data ?? []).map(r => ({ value: String(r.value), label: r.label })),
  },
  {
    key: 'construction', label: 'Construction',
    options: o => [
      ...(o.constructions.data ?? []).map(c => ({ value: c, label: c })),
      { value: NO_CONSTRUCTION, label: 'Not recorded' },
    ],
    matches: (h, v) => {
      const value = h.construction?.trim() ?? '';
      if (v === NO_CONSTRUCTION) return !value;
      // Full equality, never substring: "HYDRO" must not match "HYDROLite".
      // Case-insensitive only to tolerate rows written before the vocabulary
      // service began snapping values to one spelling on write.
      return value.toLowerCase() === v.toLowerCase();
    },
  },
];

const EMPTY: HatFilterState = {
  style: '', size: '', condition: '', type: '', color: '', room: '', construction: '',
};

/** Assign a raw string (a select, a URL) to one filter, refusing a value it cannot hold. */
function assign(state: HatFilterState, field: FilterField, raw: string): HatFilterState {
  if (raw && field.accepts && !field.accepts(raw)) return state;
  return { ...state, [field.key]: raw };
}

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
  const [filters, setFilters] = useState<HatFilterState>(() =>
    FILTER_FIELDS.reduce((acc, f) => assign(acc, f, searchParams.get(f.key) ?? ''), EMPTY));
  // Starts closed even when a link arrived with filters applied. It used to
  // open so the reason the list is short was on screen; `ActiveFilterChips`
  // now shows exactly that in one line, and a removable chip is a shorter way
  // to widen the list than opening seven selects to find the one that is set.
  // Now that filters round-trip through the URL, opening the bar on arrival
  // would also have unfolded it every time you came Back from a hat.
  const [isOpen, setIsOpen] = useState(false);

  const styles = useQuery({ queryKey: qk.meta.styles(), queryFn: getStyles });
  const sizes = useQuery({ queryKey: qk.meta.sizes(), queryFn: getSizes });
  const conditions = useQuery({ queryKey: qk.meta.conditions(), queryFn: getConditions });
  const rooms = useQuery({ queryKey: qk.meta.rooms(), queryFn: getRoomOptions });
  // Curated list merged with everything actually in use, so a specialty fabric
  // typed once is filterable from then on without shipping a migration.
  const constructions = useQuery({ queryKey: qk.meta.constructions(), queryFn: getConstructions });

  const activeCount = Object.values(filters).filter(Boolean).length;

  /** Set one filter from a raw string; a value the filter cannot hold is ignored. */
  function set(key: keyof HatFilterState, raw: string) {
    const field = FILTER_FIELDS.find(f => f.key === key);
    if (field) setFilters(prev => assign(prev, field, raw));
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
  return FILTER_FIELDS.every(field => {
    const value = f[field.key];
    return !value || !field.matches || field.matches(hat, value);
  });
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
 * under the bar re-filters as you choose. Each select has an id its `<label>`
 * points at, so the label is its accessible name AND a tap target that focuses
 * it; they used to be bare labels beside selects named by a repeated
 * `aria-label`, and tapping one did nothing.
 */
export function HatFilterBar({ state, colors, activeCount, onClearExtras, children }: FilterBarProps) {
  const { filters, set, clear, options } = state;
  const idPrefix = useId();
  const shownCount = activeCount ?? state.activeCount;
  return (
    <div className="card hr-cp-filters mb-3" role="group" aria-label="Filters">
      <div className="card-body">
        <div className="hr-cp-filter-grid">
          {FILTER_FIELDS.map(field => {
            const id = `${idPrefix}-${field.key}`;
            return (
              <div key={field.key} className="hr-cp-field">
                <label className="form-label" htmlFor={id}>{field.label}</label>
                <select
                  id={id}
                  className="form-select form-select-sm"
                  value={filters[field.key]}
                  onChange={e => set(field.key, e.target.value)}
                >
                  <option value="">All</option>
                  {field.options(options, colors).map(o => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
            );
          })}
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

/**
 * What is filtering the list, one removable chip per filter — shown while the
 * filter bar is folded away.
 *
 * Without it a filtered list looked exactly like a small collection: the only
 * sign was a digit on the Filters button, and undoing one filter meant opening
 * the bar and finding which of seven selects was set. Each chip reads its
 * words from the same option list the select shows.
 */
export function ActiveFilterChips({ state, extras = [], onClearExtras }: {
  state: FilterState;
  extras?: ExtraFilterChip[];
  /** Reset page-specific extras when "Clear all" is used. */
  onClearExtras?: () => void;
}) {
  const { filters, set, clear, options } = state;
  const chips: ExtraFilterChip[] = FILTER_FIELDS
    .filter(field => filters[field.key])
    .map(field => {
      const value = filters[field.key];
      // The current value stands in for "colors present": a color's label is
      // itself, and the chip has no result set to collect from.
      const text = optionLabel(field.options(options, [value]), value);
      return { key: field.key, label: `${field.label}: ${text}`, onRemove: () => set(field.key, '') };
    });
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
