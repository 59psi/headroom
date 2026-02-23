import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { listHats, getStyles, getSizes, getConditions } from '../api/hats';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ColorSwatches } from '../components/common/ColorSwatch';
import { ConditionBadge } from '../components/common/ConditionBadge';
import type { HatRead } from '../types';

function HatCard({ hat }: { hat: HatRead }) {
  return (
    <Link to={`/hats/${hat.id}`} className="card mb-2 text-decoration-none text-body">
      <div className="card-body d-flex gap-3">
        {hat.photo_path ? (
          <img src={`/uploads/${hat.photo_path}`} alt="" className="rounded flex-shrink-0" style={{ width: 72, height: 72, objectFit: 'cover' }} />
        ) : (
          <div className="rounded flex-shrink-0" style={{ width: 72, height: 72, background: 'var(--color-border)' }} />
        )}
        <div className="flex-grow-1" style={{ minWidth: 0 }}>
          <div className="d-flex justify-content-between align-items-start">
            <div className="fw-semibold">{hat.display_id || `#${hat.id}`}</div>
            <ConditionBadge condition={hat.condition} />
          </div>
          <div className="text-secondary small mb-1">
            {hat.style.replace(/_/g, ' ')} &middot; {hat.size.replace(/_/g, ' ')}
          </div>
          <ColorSwatches colors={hat.colors} />
        </div>
      </div>
    </Link>
  );
}

function GalleryItem({ hat }: { hat: HatRead }) {
  return (
    <Link to={`/hats/${hat.id}`} className="text-decoration-none text-body">
      <div className="card h-100">
        {hat.photo_path ? (
          <img src={`/uploads/${hat.photo_path}`} alt="" className="card-img-top hr-gallery-item" />
        ) : (
          <div className="hr-gallery-placeholder">No photo</div>
        )}
        <div className="card-body py-2 px-2">
          <div className="fw-semibold small">{hat.display_id || `#${hat.id}`}</div>
          <div className="text-secondary" style={{ fontSize: '0.75rem' }}>
            {hat.style.replace(/_/g, ' ')}
          </div>
          <ColorSwatches colors={hat.colors} />
        </div>
      </div>
    </Link>
  );
}

export function HatsPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['hats'], queryFn: () => listHats() });
  const stylesQ = useQuery({ queryKey: ['meta', 'styles'], queryFn: getStyles });
  const sizesQ = useQuery({ queryKey: ['meta', 'sizes'], queryFn: getSizes });
  const conditionsQ = useQuery({ queryKey: ['meta', 'conditions'], queryFn: getConditions });

  const [view, setView] = useState<'list' | 'gallery'>('gallery');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filterStyle, setFilterStyle] = useState('');
  const [filterSize, setFilterSize] = useState('');
  const [filterCondition, setFilterCondition] = useState('');
  const [filterType, setFilterType] = useState('');

  const activeFilterCount = [filterStyle, filterSize, filterCondition, filterType].filter(Boolean).length;

  const filteredData = useMemo(() => {
    if (!data) return [];
    return data.filter(h => {
      if (filterStyle && h.style !== filterStyle) return false;
      if (filterSize && h.size !== filterSize) return false;
      if (filterCondition && h.condition !== filterCondition) return false;
      if (filterType === 'beanie' && !h.is_beanie) return false;
      if (filterType === 'regular' && h.is_beanie) return false;
      return true;
    });
  }, [data, filterStyle, filterSize, filterCondition, filterType]);

  if (isLoading) return <LoadingSpinner />;
  if (error) return <div className="alert alert-danger">{String(error)}</div>;

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h1>Hats</h1>
        <div className="d-flex gap-2 align-items-center">
          <button
            type="button"
            className={`btn btn-sm ${activeFilterCount ? 'btn-primary' : 'btn-outline-secondary'}`}
            onClick={() => setFiltersOpen(!filtersOpen)}
          >
            Filters{activeFilterCount > 0 && <span className="badge bg-white text-primary ms-1">{activeFilterCount}</span>}
          </button>
          <div className="btn-group btn-group-sm" role="group">
            <button
              type="button"
              className={`btn ${view === 'list' ? 'btn-primary' : 'btn-outline-primary'}`}
              onClick={() => setView('list')}
              title="List view"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><rect x="0" y="1" width="16" height="3" rx="1"/><rect x="0" y="6.5" width="16" height="3" rx="1"/><rect x="0" y="12" width="16" height="3" rx="1"/></svg>
            </button>
            <button
              type="button"
              className={`btn ${view === 'gallery' ? 'btn-primary' : 'btn-outline-primary'}`}
              onClick={() => setView('gallery')}
              title="Gallery view"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><rect x="0" y="0" width="7" height="7" rx="1"/><rect x="9" y="0" width="7" height="7" rx="1"/><rect x="0" y="9" width="7" height="7" rx="1"/><rect x="9" y="9" width="7" height="7" rx="1"/></svg>
            </button>
          </div>
          <Link to="/hats/new" className="btn btn-primary btn-sm">+ New</Link>
        </div>
      </div>

      {filtersOpen && (
        <div className="card mb-3">
          <div className="card-body">
            <div className="row g-2">
              <div className="col-6 col-md-3">
                <label className="form-label small text-secondary mb-1">Style</label>
                <select className="form-select form-select-sm" value={filterStyle} onChange={e => setFilterStyle(e.target.value)}>
                  <option value="">All</option>
                  {stylesQ.data?.map(s => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div className="col-6 col-md-3">
                <label className="form-label small text-secondary mb-1">Size</label>
                <select className="form-select form-select-sm" value={filterSize} onChange={e => setFilterSize(e.target.value)}>
                  <option value="">All</option>
                  {sizesQ.data?.map(s => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div className="col-6 col-md-3">
                <label className="form-label small text-secondary mb-1">Condition</label>
                <select className="form-select form-select-sm" value={filterCondition} onChange={e => setFilterCondition(e.target.value)}>
                  <option value="">All</option>
                  {conditionsQ.data?.map(c => (
                    <option key={c.value} value={c.value}>{c.label}</option>
                  ))}
                </select>
              </div>
              <div className="col-6 col-md-3">
                <label className="form-label small text-secondary mb-1">Type</label>
                <select className="form-select form-select-sm" value={filterType} onChange={e => setFilterType(e.target.value)}>
                  <option value="">All</option>
                  <option value="regular">Regular</option>
                  <option value="beanie">Beanies</option>
                </select>
              </div>
            </div>
            {activeFilterCount > 0 && (
              <button
                type="button"
                className="btn btn-link btn-sm text-danger mt-2 p-0"
                onClick={() => { setFilterStyle(''); setFilterSize(''); setFilterCondition(''); setFilterType(''); }}
              >Clear filters</button>
            )}
          </div>
        </div>
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
        filteredData.map(h => <HatCard key={h.id} hat={h} />)
      )}
    </>
  );
}
