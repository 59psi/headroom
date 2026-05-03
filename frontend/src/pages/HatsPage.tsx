import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { listHats, getStyles, getSizes, getConditions } from '../api/hats';
import { getRoomOptions } from '../api/rooms';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ColorSwatches } from '../components/common/ColorSwatch';
import { ConditionBadge } from '../components/common/ConditionBadge';
import type { HatRead } from '../types';

function HatRow({ hat }: { hat: HatRead }) {
  return (
    <Link to={`/hats/${hat.id}`} className="card mb-2 text-decoration-none">
      <div className="card-body d-flex gap-3 align-items-center">
        {hat.photo_path ? (
          <img src={`/uploads/${hat.photo_path}`} alt="" className="hr-thumb flex-shrink-0" style={{ width: 80, height: 80 }} />
        ) : (
          <div className="rounded flex-shrink-0" style={{ width: 80, height: 80, background: 'rgba(0,0,0,0.3)', border: '1px dashed var(--border)' }} />
        )}
        <div className="flex-grow-1" style={{ minWidth: 0 }}>
          <div className="d-flex justify-content-between align-items-start gap-2">
            <div>
              <div className="fw-bold font-mono" style={{ color: 'var(--neon-cyan)' }}>{hat.display_id || `#${hat.id}`}</div>
              {hat.brand && (
                <div className="text-secondary small">
                  <span style={{ color: 'var(--neon-pink)' }}>{hat.brand}</span>
                  {hat.model_name && <> · {hat.model_name}</>}
                </div>
              )}
            </div>
            <ConditionBadge condition={hat.condition} />
          </div>
          <div className="text-muted small mb-1" style={{ marginTop: 4 }}>
            {hat.style.replace(/_/g, ' ')} · {hat.size.replace(/_/g, ' ')}
            {hat.room_name && <> · {hat.room_name}</>}
          </div>
          <ColorSwatches colors={hat.colors} showLabels={false} />
        </div>
      </div>
    </Link>
  );
}

function GalleryItem({ hat }: { hat: HatRead }) {
  return (
    <Link to={`/hats/${hat.id}`} className="card text-decoration-none h-100">
      {hat.photo_path ? (
        <img src={`/uploads/${hat.photo_path}`} alt="" className="hr-gallery-item" />
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
  const { data, isLoading, error } = useQuery({ queryKey: ['hats'], queryFn: () => listHats() });
  const stylesQ = useQuery({ queryKey: ['meta', 'styles'], queryFn: getStyles });
  const sizesQ = useQuery({ queryKey: ['meta', 'sizes'], queryFn: getSizes });
  const conditionsQ = useQuery({ queryKey: ['meta', 'conditions'], queryFn: getConditions });
  const roomsQ = useQuery({ queryKey: ['meta', 'rooms'], queryFn: getRoomOptions });

  const [view, setView] = useState<'list' | 'gallery'>('gallery');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filterStyle, setFilterStyle] = useState('');
  const [filterSize, setFilterSize] = useState('');
  const [filterCondition, setFilterCondition] = useState('');
  const [filterType, setFilterType] = useState('');
  const [filterColor, setFilterColor] = useState('');
  const [filterRoom, setFilterRoom] = useState('');
  const [filterBrand, setFilterBrand] = useState('');

  const activeFilterCount = [filterStyle, filterSize, filterCondition, filterType, filterColor, filterRoom, filterBrand].filter(Boolean).length;

  const availableColors = useMemo(() => {
    if (!data) return [];
    const colors = new Set<string>();
    data.forEach(h => h.colors.forEach(c => {
      if (c.general_color) colors.add(c.general_color);
    }));
    return [...colors].sort();
  }, [data]);

  const availableBrands = useMemo(() => {
    if (!data) return [];
    return [...new Set(data.map(h => h.brand).filter(Boolean) as string[])].sort();
  }, [data]);

  const filteredData = useMemo(() => {
    if (!data) return [];
    return data.filter(h => {
      if (filterStyle && h.style !== filterStyle) return false;
      if (filterSize && h.size !== filterSize) return false;
      if (filterCondition && h.condition !== filterCondition) return false;
      if (filterType === 'beanie' && !h.is_beanie) return false;
      if (filterType === 'regular' && h.is_beanie) return false;
      if (filterColor && !h.colors.some(c => c.general_color === filterColor)) return false;
      if (filterRoom && h.room_id !== Number(filterRoom)) return false;
      if (filterBrand && h.brand !== filterBrand) return false;
      return true;
    });
  }, [data, filterStyle, filterSize, filterCondition, filterType, filterColor, filterRoom, filterBrand]);

  if (isLoading) return <LoadingSpinner />;
  if (error) return (
    <div className="text-center py-5">
      <h5 className="mb-2">No hats to display</h5>
      <p className="text-secondary small mb-3">The hat collection is empty or could not be loaded.</p>
      <Link to="/hats/new" className="btn btn-primary">Add First Hat</Link>
    </div>
  );

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3 gap-2 flex-wrap">
        <h1>Hats</h1>
        <div className="d-flex gap-2 align-items-center">
          <button
            type="button"
            className={`btn btn-sm ${activeFilterCount ? 'btn-primary' : 'btn-outline-secondary'}`}
            onClick={() => setFiltersOpen(!filtersOpen)}
          >
            Filters{activeFilterCount > 0 && <span className="badge bg-white ms-1">{activeFilterCount}</span>}
          </button>
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
          <Link to="/hats/new" className="btn btn-primary btn-sm">+ New</Link>
        </div>
      </div>

      {filtersOpen && (
        <div className="card mb-3">
          <div className="card-body">
            <div className="row g-2">
              <div className="col-6 col-md-3">
                <label className="form-label">Style</label>
                <select className="form-select form-select-sm" value={filterStyle} onChange={e => setFilterStyle(e.target.value)}>
                  <option value="">All</option>
                  {stylesQ.data?.map(s => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div className="col-6 col-md-3">
                <label className="form-label">Size</label>
                <select className="form-select form-select-sm" value={filterSize} onChange={e => setFilterSize(e.target.value)}>
                  <option value="">All</option>
                  {sizesQ.data?.map(s => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div className="col-6 col-md-3">
                <label className="form-label">Condition</label>
                <select className="form-select form-select-sm" value={filterCondition} onChange={e => setFilterCondition(e.target.value)}>
                  <option value="">All</option>
                  {conditionsQ.data?.map(c => (
                    <option key={c.value} value={c.value}>{c.label}</option>
                  ))}
                </select>
              </div>
              <div className="col-6 col-md-3">
                <label className="form-label">Type</label>
                <select className="form-select form-select-sm" value={filterType} onChange={e => setFilterType(e.target.value)}>
                  <option value="">All</option>
                  <option value="regular">Regular</option>
                  <option value="beanie">Beanies</option>
                </select>
              </div>
              <div className="col-6 col-md-3">
                <label className="form-label">Color</label>
                <select className="form-select form-select-sm" value={filterColor} onChange={e => setFilterColor(e.target.value)}>
                  <option value="">All</option>
                  {availableColors.map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>
              <div className="col-6 col-md-3">
                <label className="form-label">Room</label>
                <select className="form-select form-select-sm" value={filterRoom} onChange={e => setFilterRoom(e.target.value)}>
                  <option value="">All</option>
                  {roomsQ.data?.map(r => (
                    <option key={r.value} value={r.value}>{r.label}</option>
                  ))}
                </select>
              </div>
              {availableBrands.length > 0 && (
                <div className="col-6 col-md-3">
                  <label className="form-label">Brand</label>
                  <select className="form-select form-select-sm" value={filterBrand} onChange={e => setFilterBrand(e.target.value)}>
                    <option value="">All</option>
                    {availableBrands.map(b => (
                      <option key={b} value={b}>{b}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
            {activeFilterCount > 0 && (
              <button
                type="button"
                className="btn btn-link btn-sm mt-2 p-0"
                style={{ color: 'var(--neon-red)' }}
                onClick={() => { setFilterStyle(''); setFilterSize(''); setFilterCondition(''); setFilterType(''); setFilterColor(''); setFilterRoom(''); setFilterBrand(''); }}
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
        filteredData.map(h => <HatRow key={h.id} hat={h} />)
      )}
    </>
  );
}
