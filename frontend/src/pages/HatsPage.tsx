import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { listAllHats } from '../api/hats';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ColorSwatches } from '../components/common/ColorSwatch';
import {
  useHatFilters, HatFilterBar, FilterToggleButton,
  collectGeneralColors, matchesHatFilters,
} from '../components/hats/HatFilters';
import type { HatRead } from '../types';
import { tileSrc } from '../lib/photo';
import { placementOf, type Placement } from '../lib/placement';
import { HatRow } from '../components/hats/HatRow';

function GalleryItem({ hat }: { hat: HatRead }) {
  return (
    <Link to={`/hats/${hat.id}`} className="card text-decoration-none h-100">
      {hat.photo_path ? (
        <img src={tileSrc(hat)} alt="" className="hr-gallery-item" />
      ) : (
        <div className="hr-gallery-placeholder">No photo</div>
      )}
      <div className="card-body py-2 px-2">
        <div className="fw-bold font-mono small" style={{ color: 'var(--neon-cyan)' }}>
          {hat.display_id || `#${hat.id}`}
        </div>
        {hat.brand && (
          <div className="small" style={{ color: 'var(--neon-pink)', fontSize: '0.75rem', marginTop: 2 }}>
            {hat.brand}{hat.model_name ? ` · ${hat.model_name}` : ''}
          </div>
        )}
        <div className="text-muted" style={{ fontSize: '0.72rem', marginTop: 2 }}>
          {hat.style.replace(/_/g, ' ')}
        </div>
        <ColorSwatches colors={hat.colors} showLabels={false} />
      </div>
    </Link>
  );
}

export function HatsPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['hats'], queryFn: listAllHats });
  const hatFilters = useHatFilters();
  const { filters, isOpen: filtersOpen, setIsOpen: setFiltersOpen } = hatFilters;

  const [view, setView] = useState<'list' | 'gallery'>('gallery');
  const [filterBrand, setFilterBrand] = useState('');
  // 'all' (default) or one of the three placements — see `lib/placement`.
  const [filterAssignment, setFilterAssignment] = useState<'all' | Placement>('all');

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

  if (isLoading) return <LoadingSpinner />;
  // A failed fetch must not render as an empty collection — Home, Valuation
  // and Stats each say so, and this page still offered "Add First Hat" over a
  // 500. An error is shown as an error; the empty state below is for a
  // collection that really is empty.
  if (error) return (
    <div className="alert alert-danger" role="alert">
      Couldn&rsquo;t load your hats. Reload to try again.
    </div>
  );

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3 gap-2 flex-wrap">
        <h1>Hats</h1>
        <div className="d-flex gap-2 align-items-center">
          <FilterToggleButton
            activeCount={activeFilterCount}
            isOpen={filtersOpen}
            onToggle={setFiltersOpen}
          />
          <div className="btn-group" role="group">
            <button
              type="button"
              className={`btn btn-sm ${view === 'list' ? 'btn-primary' : 'btn-outline-primary'}`}
              onClick={() => setView('list')}
              title="List view"
              aria-label="List view"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><rect x="0" y="1" width="16" height="3" rx="1"/><rect x="0" y="6.5" width="16" height="3" rx="1"/><rect x="0" y="12" width="16" height="3" rx="1"/></svg>
            </button>
            <button
              type="button"
              className={`btn btn-sm ${view === 'gallery' ? 'btn-primary' : 'btn-outline-primary'}`}
              onClick={() => setView('gallery')}
              title="Gallery view"
              aria-label="Gallery view"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><rect x="0" y="0" width="7" height="7" rx="1"/><rect x="9" y="0" width="7" height="7" rx="1"/><rect x="0" y="9" width="7" height="7" rx="1"/><rect x="9" y="9" width="7" height="7" rx="1"/></svg>
            </button>
          </div>
          <Link to="/hats/import" className="btn btn-outline-primary btn-sm" title="Bulk import">⇪</Link>
          <Link to="/hats/new" className="btn btn-primary btn-sm">+ New</Link>
        </div>
      </div>

      {/* Quick chips: where the hat is. "In a room" only appears once a hat
          is kept that way, so a collection that is all cases sees two chips. */}
      {(unassignedCount > 0 || placementCounts.room > 0 || filterAssignment !== 'all') && (
        <div className="d-flex gap-2 mb-3 flex-wrap">
          <button
            type="button"
            className={`btn btn-sm ${filterAssignment === 'all' ? 'btn-primary' : 'btn-outline-secondary'}`}
            onClick={() => setFilterAssignment('all')}
          >All</button>
          <button
            type="button"
            className={`btn btn-sm ${filterAssignment === 'case' ? 'btn-primary' : 'btn-outline-secondary'}`}
            onClick={() => setFilterAssignment('case')}
          >In a Case</button>
          {(placementCounts.room > 0 || filterAssignment === 'room') && (
            <button
              type="button"
              className={`btn btn-sm ${filterAssignment === 'room' ? 'btn-primary' : 'btn-outline-secondary'}`}
              onClick={() => setFilterAssignment('room')}
            >
              In a Room
              {placementCounts.room > 0 && (
                <span className="badge bg-white ms-1">{placementCounts.room}</span>
              )}
            </button>
          )}
          <button
            type="button"
            className={`btn btn-sm ${filterAssignment === 'none' ? 'btn-primary' : 'btn-outline-secondary'}`}
            onClick={() => setFilterAssignment('none')}
          >
            Unassigned
            {unassignedCount > 0 && (
              <span className="badge bg-white ms-1">{unassignedCount}</span>
            )}
          </button>
        </div>
      )}

      {filtersOpen && (
        <HatFilterBar
          state={hatFilters}
          colors={availableColors}
          activeCount={activeFilterCount}
          onClearExtras={() => { setFilterBrand(''); setFilterAssignment('all'); }}
        >
          {availableBrands.length > 0 && (
            <div className="col-6 col-md-3">
              <label className="form-label">Brand</label>
              <select aria-label="Brand" className="form-select form-select-sm" value={filterBrand} onChange={e => setFilterBrand(e.target.value)}>
                <option value="">All</option>
                {availableBrands.map(b => (
                  <option key={b} value={b}>{b}</option>
                ))}
              </select>
            </div>
          )}
        </HatFilterBar>
      )}

      {!filteredData.length ? (
        <div className="text-center py-5 text-secondary">
          <p className="mb-3">{data?.length ? 'No matching hats' : 'No hats yet'}</p>
          {!data?.length && <Link to="/hats/new" className="btn btn-primary">Add First Hat</Link>}
        </div>
      ) : view === 'gallery' ? (
        <div className="row row-cols-2 row-cols-md-3 row-cols-lg-4 g-3">
          {filteredData.map(h => (
            <div className="col" key={h.id}><GalleryItem hat={h} /></div>
          ))}
        </div>
      ) : (
        filteredData.map(h => <HatRow key={h.id} hat={h} />)
      )}
    </>
  );
}
