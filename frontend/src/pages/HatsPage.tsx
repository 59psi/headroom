import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router';
import { listAllHats } from '../api/hats';
import { ColorSwatches } from '../components/common/ColorSwatch';
import {
  useHatFilters, HatFilterBar, FilterToggleButton, ActiveFilterChips, useMirrorToUrl,
  collectGeneralColors, matchesHatFilters, type ExtraFilterChip,
} from '../components/hats/HatFilters';
import type { HatRead } from '../types';
import { tileSrc } from '../lib/photo';
import { useHatLabels } from '../lib/labels';
import { hatName, placementOf, type Placement } from '../lib/placement';
import { qk } from '../lib/queryKeys';
import { LoadError } from '../components/common/LoadError';
import { HatRow } from '../components/hats/HatRow';
import { PageHeader } from '../components/ui/PageHeader';
import { Segmented, type SegmentedOption } from '../components/ui/Segmented';

type View = 'list' | 'gallery';

/**
 * The list/gallery choice, remembered per device.
 *
 * A preference, not shared state: someone who reads their collection as a list
 * on a phone may want the gallery on the iPad. Every access is guarded —
 * storage throws in some private modes, and a lost preference must degrade to
 * the default rather than take the page down.
 */
const VIEW_KEY = 'headroom.hats.view';

function readView(): View {
  try {
    return window.localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'gallery';
  } catch {
    return 'gallery';
  }
}

function writeView(v: View) {
  try {
    window.localStorage.setItem(VIEW_KEY, v);
  } catch {
    // Private mode or blocked storage: the choice lasts for this visit only.
  }
}

/** Two glyphs everyone reads the same way; the label is each button's name
 *  and tooltip. */
const VIEW_OPTIONS: ReadonlyArray<SegmentedOption<View>> = [
  {
    value: 'list',
    label: 'List view',
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><rect x="0" y="1" width="16" height="3" rx="1"/><rect x="0" y="6.5" width="16" height="3" rx="1"/><rect x="0" y="12" width="16" height="3" rx="1"/></svg>,
  },
  {
    value: 'gallery',
    label: 'Gallery view',
    icon: <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><rect x="0" y="0" width="7" height="7" rx="1"/><rect x="9" y="0" width="7" height="7" rx="1"/><rect x="0" y="9" width="7" height="7" rx="1"/><rect x="9" y="9" width="7" height="7" rx="1"/></svg>,
  },
];

const PLACEMENTS: readonly Placement[] = ['case', 'room', 'none'];

function readPlacement(v: string | null): 'all' | Placement {
  return PLACEMENTS.includes(v as Placement) ? (v as Placement) : 'all';
}

function GalleryItem({ hat }: { hat: HatRead }) {
  const labels = useHatLabels();
  // What the list row calls it (`hatName`) — a loose hat by its model, where
  // this tile said "#12" — and the model not repeated under it when it IS
  // the headline.
  const headline = hatName(hat);
  const modelInSub = hat.model_name && hat.model_name !== headline;
  return (
    <Link to={`/hats/${hat.id}`} className="card hr-cp-tile">
      {hat.photo_path ? (
        <img src={tileSrc(hat)} alt="" className="hr-gallery-item" />
      ) : (
        <div className="hr-gallery-placeholder">No photo</div>
      )}
      <div className="hr-cp-tile-body">
        <div className="hr-cp-tile-id">{headline}</div>
        {hat.brand && (
          <div className="hr-cp-tile-name">
            {hat.brand}{modelInSub ? ` · ${hat.model_name}` : ''}
          </div>
        )}
        <div className="hr-cp-tile-meta">{labels.style(hat.style)}</div>
        <ColorSwatches colors={hat.colors} showLabels={false} />
      </div>
    </Link>
  );
}

/**
 * The page in the shape it is about to have, in whichever view is chosen.
 * One status region for the whole grid, so it is announced once.
 */
function HatsSkeleton({ view }: { view: View }) {
  const count = view === 'gallery' ? 8 : 5;
  return (
    <div className={view === 'gallery' ? 'hr-cp-gallery' : 'hr-cp-list'} role="status" aria-live="polite">
      <span className="visually-hidden">Loading hats…</span>
      {Array.from({ length: count }, (_, i) =>
        view === 'gallery' ? (
          <div key={i} className="card hr-cp-tile" aria-hidden="true">
            <span className="hr-skeleton hr-cp-skel-photo" />
            <div className="hr-cp-tile-body">
              <span className="hr-skeleton hr-skeleton-line hr-cp-skel-w55" />
              <span className="hr-skeleton hr-skeleton-line hr-cp-skel-w35" />
            </div>
          </div>
        ) : (
          <div key={i} className="card hr-cp-row" aria-hidden="true">
            <div className="card-body hr-cp-row-body">
              <span className="hr-skeleton hr-cp-row-thumb hr-cp-skel-thumb" />
              <div className="hr-cp-row-main hr-cp-skel-stack">
                <span className="hr-skeleton hr-skeleton-line hr-cp-skel-w35" />
                <span className="hr-skeleton hr-skeleton-line hr-cp-skel-w55" />
                <span className="hr-skeleton hr-skeleton-line hr-cp-skel-w75" />
              </div>
            </div>
          </div>
        ),
      )}
    </div>
  );
}

export function HatsPage() {
  const hatsQ = useQuery({ queryKey: qk.hats(), queryFn: listAllHats });
  const { data, isLoading, error } = hatsQ;
  const hatFilters = useHatFilters();
  const { filters, isOpen: filtersOpen, setIsOpen: setFiltersOpen } = hatFilters;

  // Brand and placement are this page's own filters (Search has neither), so
  // they are seeded from the URL here rather than in the shared hook — same
  // rule: read once on arrival, the controls own them after that.
  const [searchParams] = useSearchParams();
  const [view, setViewState] = useState<View>(readView);
  const [filterBrand, setFilterBrand] = useState(() => searchParams.get('brand') ?? '');
  // 'all' (default) or one of the three placements — see `lib/placement`.
  const [filterAssignment, setFilterAssignment] = useState<'all' | Placement>(
    () => readPlacement(searchParams.get('placement')),
  );

  useMirrorToUrl({
    ...filters,
    brand: filterBrand,
    placement: filterAssignment === 'all' ? '' : filterAssignment,
  });

  function setView(v: View) {
    setViewState(v);
    writeView(v);
  }

  function clearExtras() {
    setFilterBrand('');
    setFilterAssignment('all');
  }

  function clearEverything() {
    hatFilters.clear();
    clearExtras();
  }

  const activeFilterCount =
    hatFilters.activeCount + (filterBrand ? 1 : 0) + (filterAssignment === 'all' ? 0 : 1);

  const placementCounts = useMemo(() => {
    const counts: Record<Placement, number> = { case: 0, room: 0, none: 0 };
    for (const h of data ?? []) counts[placementOf(h)]++;
    return counts;
  }, [data]);
  const unassignedCount = placementCounts.none;

  const availableColors = useMemo(() => collectGeneralColors(data), [data]);

  const availableBrands = useMemo(() => {
    if (!data) return [];
    return [...new Set(data.map(h => h.brand).filter(Boolean) as string[])].sort();
  }, [data]);

  const filteredData = useMemo(() => {
    if (!data) return [];
    return data.filter(h => {
      if (!matchesHatFilters(h, filters)) return false;
      // Room is matched client-side here (the Search page sends it to the API
      // instead), so it isn't part of the shared predicate.
      if (filters.room && h.room_id !== Number(filters.room)) return false;
      if (filterBrand && h.brand !== filterBrand) return false;
      if (filterAssignment !== 'all' && placementOf(h) !== filterAssignment) return false;
      return true;
    });
  }, [data, filters, filterBrand, filterAssignment]);

  const brandChip: ExtraFilterChip[] = filterBrand
    ? [{ key: 'brand', label: `Brand: ${filterBrand}`, onRemove: () => setFilterBrand('') }]
    : [];

  // "12 of 128" while anything narrows the list — the live count is the
  // acknowledgement that a filter took, since there is no Apply button.
  const total = data?.length ?? 0;
  const countText = data
    ? filteredData.length === total ? `${total}` : `${filteredData.length} of ${total}`
    : '';

  // Where the hat is. "In a room" only appears once a hat is kept that way
  // (or while it is the filter in force, so it can still be seen and turned
  // off) — a collection with nothing in a room is not offered a chip that
  // could only empty the page. Counts mark the placements worth a second
  // look, and only when non-zero.
  const placementOptions: SegmentedOption<'all' | Placement>[] = [
    { value: 'all', label: 'All' },
    { value: 'case', label: 'In a case' },
    ...(placementCounts.room > 0 || filterAssignment === 'room'
      ? [{ value: 'room' as const, label: 'In a room', count: placementCounts.room || undefined }]
      : []),
    { value: 'none', label: 'Unassigned', count: unassignedCount || undefined },
  ];

  const header = (
    <PageHeader
      title="Hats"
      count={countText && <>{countText}<span className="visually-hidden"> hats</span></>}
      actions={
        <>
          <Link to="/hats/import" className="btn btn-outline-secondary btn-sm" aria-label="Bulk import" title="Bulk import">
            <svg className="hr-cp-icon" width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M8 11V2.5M4.5 6 8 2.5 11.5 6M2.5 13.5h11" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Import
          </Link>
          <Link to="/hats/new" className="btn btn-primary btn-sm">Add hat</Link>
        </>
      }
    />
  );

  // A failed fetch must not render as an empty collection — Home, Valuation
  // and Stats each say so, and this page still offered "Add First Hat" over a
  // 500. An error is shown as an error; the empty state below is for a
  // collection that really is empty. Retrying is a refetch in place rather
  // than a full reload of the app.
  if (error) {
    return (
      <>
        {header}
        <LoadError what="Couldn’t load your hats." queries={[hatsQ]} />
      </>
    );
  }

  return (
    <>
      {header}

      <div className="hr-cp-toolbar">
        <FilterToggleButton
          activeCount={activeFilterCount}
          isOpen={filtersOpen}
          onToggle={setFiltersOpen}
        />
        {/* Quick chips: where the hat is. Only once there is a choice to
            make — a collection that is all in cases has nothing to narrow. */}
        {!isLoading && (unassignedCount > 0 || placementCounts.room > 0 || filterAssignment !== 'all') && (
          <Segmented
            variant="chips"
            label="Where the hat is kept"
            options={placementOptions}
            value={filterAssignment}
            onChange={setFilterAssignment}
          />
        )}
        <Segmented
          label="View"
          iconOnly
          className="hr-cp-toolbar-end"
          options={VIEW_OPTIONS}
          value={view}
          onChange={setView}
        />
      </div>

      {filtersOpen ? (
        <HatFilterBar
          state={hatFilters}
          colors={availableColors}
          activeCount={activeFilterCount}
          onClearExtras={clearExtras}
        >
          {availableBrands.length > 0 && (
            <div className="hr-cp-field">
              {/* Tied to its select by id, so tapping the word focuses the
                  control and the select's name IS the visible label — not a
                  separate `aria-label` restating it. */}
              <label className="form-label" htmlFor="hats-filter-brand">Brand</label>
              <select id="hats-filter-brand" className="form-select form-select-sm" value={filterBrand} onChange={e => setFilterBrand(e.target.value)}>
                <option value="">All</option>
                {availableBrands.map(b => (
                  <option key={b} value={b}>{b}</option>
                ))}
              </select>
            </div>
          )}
        </HatFilterBar>
      ) : (
        <ActiveFilterChips state={hatFilters} extras={brandChip} onClearExtras={clearExtras} />
      )}

      {isLoading ? (
        <HatsSkeleton view={view} />
      ) : !filteredData.length ? (
        data?.length ? (
          <div className="hr-cp-empty">
            <div className="hr-cp-empty-title">No hats match these filters</div>
            <p>{total} {total === 1 ? 'hat is' : 'hats are'} hidden by what&rsquo;s selected above.</p>
            <div className="hr-cp-empty-actions">
              <button type="button" className="btn btn-outline-secondary" onClick={clearEverything}>
                Show all hats
              </button>
            </div>
          </div>
        ) : (
          <div className="hr-cp-empty">
            <div className="hr-cp-empty-title">No hats yet</div>
            <p>Add one from a photo, or bring in a batch at once.</p>
            <div className="hr-cp-empty-actions">
              <Link to="/hats/new" className="btn btn-primary">Add first hat</Link>
              <Link to="/hats/import" className="btn btn-outline-secondary">Bulk import</Link>
            </div>
          </div>
        )
      ) : view === 'gallery' ? (
        <div className="hr-cp-gallery">
          {filteredData.map(h => <GalleryItem key={h.id} hat={h} />)}
        </div>
      ) : (
        <div className="hr-cp-list">
          {filteredData.map(h => <HatRow key={h.id} hat={h} />)}
        </div>
      )}
    </>
  );
}
