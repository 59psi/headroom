import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { searchHats } from '../api/search';
import { getStyles, getSizes, getConditions } from '../api/hats';
import { getRoomOptions } from '../api/rooms';
import { ColorSwatches } from '../components/common/ColorSwatch';
import { ConditionBadge } from '../components/common/ConditionBadge';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

export function SearchPage() {
  const [query, setQuery] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [exactColors, setExactColors] = useState(false);

  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filterStyle, setFilterStyle] = useState('');
  const [filterSize, setFilterSize] = useState('');
  const [filterCondition, setFilterCondition] = useState('');
  const [filterType, setFilterType] = useState('');
  const [filterColor, setFilterColor] = useState('');
  const [filterRoom, setFilterRoom] = useState('');

  const stylesQ = useQuery({ queryKey: ['meta', 'styles'], queryFn: getStyles });
  const sizesQ = useQuery({ queryKey: ['meta', 'sizes'], queryFn: getSizes });
  const conditionsQ = useQuery({ queryKey: ['meta', 'conditions'], queryFn: getConditions });
  const roomsQ = useQuery({ queryKey: ['meta', 'rooms'], queryFn: getRoomOptions });

  const roomIdParam = filterRoom ? Number(filterRoom) : undefined;

  const { data, isLoading, error } = useQuery({
    queryKey: ['search', searchTerm, exactColors, roomIdParam],
    queryFn: () => searchHats(searchTerm, exactColors, roomIdParam),
    enabled: searchTerm.length > 0,
  });

  const activeFilterCount = [filterStyle, filterSize, filterCondition, filterType, filterColor, filterRoom].filter(Boolean).length;

  const availableColors = useMemo(() => {
    if (!data) return [];
    const colors = new Set<string>();
    data.forEach(h => h.colors.forEach(c => {
      if (c.general_color) colors.add(c.general_color);
    }));
    return [...colors].sort();
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
      return true;
    });
  }, [data, filterStyle, filterSize, filterCondition, filterType, filterColor]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSearchTerm(query.trim());
  }

  function clearFilters() {
    setFilterStyle(''); setFilterSize(''); setFilterCondition('');
    setFilterType(''); setFilterColor(''); setFilterRoom('');
  }

  return (
    <>
      <h1 className="mb-3">Search</h1>

      <form onSubmit={handleSubmit} className="mb-3">
        <div className="input-group">
          <input
            type="search"
            className="form-control"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Color, brand, style, size, room…"
          />
          <button type="submit" className="btn btn-primary">GO</button>
        </div>
        <div className="d-flex align-items-center gap-2 mt-2">
          <input
            type="checkbox"
            className="form-check-input"
            id="exactColors"
            checked={exactColors}
            onChange={e => setExactColors(e.target.checked)}
            style={{ marginTop: 0 }}
          />
          <label className="form-check-label small text-secondary mb-0" htmlFor="exactColors">
            Match exact color names (e.g. <span className="font-mono">darkslategray</span>)
          </label>
        </div>
      </form>

      {!searchTerm && (
        <div className="text-center py-5 text-secondary">
          <p>Search across every hat by color, brand, style, condition, size, or room</p>
          <p className="small">Multi-term AND: <span className="font-mono">blue a_game</span></p>
        </div>
      )}

      {isLoading && <LoadingSpinner label="Searching" />}
      {error && <div className="alert alert-danger">{String(error)}</div>}

      {data && searchTerm && (
        <>
          <div className="d-flex justify-content-between align-items-center mb-3 gap-2 flex-wrap">
            <div className="text-secondary small font-mono">
              {filteredData.length} of {data.length} result{data.length !== 1 ? 's' : ''} for "{searchTerm}"
            </div>
            {data.length > 0 && (
              <button
                type="button"
                className={`btn btn-sm ${activeFilterCount ? 'btn-primary' : 'btn-outline-secondary'}`}
                onClick={() => setFiltersOpen(!filtersOpen)}
              >
                Filters{activeFilterCount > 0 && <span className="badge bg-white ms-1">{activeFilterCount}</span>}
              </button>
            )}
          </div>

          {filtersOpen && data.length > 0 && (
            <div className="card mb-3">
              <div className="card-body">
                <div className="row g-2">
                  <div className="col-6 col-md-3">
                    <label className="form-label">Style</label>
                    <select className="form-select form-select-sm" value={filterStyle} onChange={e => setFilterStyle(e.target.value)}>
                      <option value="">All</option>
                      {stylesQ.data?.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                    </select>
                  </div>
                  <div className="col-6 col-md-3">
                    <label className="form-label">Size</label>
                    <select className="form-select form-select-sm" value={filterSize} onChange={e => setFilterSize(e.target.value)}>
                      <option value="">All</option>
                      {sizesQ.data?.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                    </select>
                  </div>
                  <div className="col-6 col-md-3">
                    <label className="form-label">Condition</label>
                    <select className="form-select form-select-sm" value={filterCondition} onChange={e => setFilterCondition(e.target.value)}>
                      <option value="">All</option>
                      {conditionsQ.data?.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
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
                      {availableColors.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </div>
                  <div className="col-6 col-md-3">
                    <label className="form-label">Room</label>
                    <select className="form-select form-select-sm" value={filterRoom} onChange={e => setFilterRoom(e.target.value)}>
                      <option value="">All</option>
                      {roomsQ.data?.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                    </select>
                  </div>
                </div>
                {activeFilterCount > 0 && (
                  <button
                    type="button"
                    className="btn btn-link btn-sm mt-2 p-0"
                    style={{ color: 'var(--neon-red)' }}
                    onClick={clearFilters}
                  >Clear filters</button>
                )}
              </div>
            </div>
          )}

          {filteredData.length === 0 ? (
            <div className="text-center py-5 text-secondary">
              <p>{activeFilterCount > 0 ? 'No results match your filters' : 'No hats found'}</p>
            </div>
          ) : (
            filteredData.map(hat => (
              <Link key={hat.id} to={`/hats/${hat.id}`} className="card mb-2 text-decoration-none">
                <div className="card-body d-flex gap-3 align-items-center">
                  {hat.photo_path ? (
                    <img src={`/uploads/${hat.photo_path}`} alt="" className="hr-thumb flex-shrink-0" style={{ width: 72, height: 72 }} />
                  ) : (
                    <div className="rounded flex-shrink-0" style={{ width: 72, height: 72, background: 'rgba(0,0,0,0.3)', border: '1px dashed var(--border)' }} />
                  )}
                  <div className="flex-grow-1" style={{ minWidth: 0 }}>
                    <div className="d-flex justify-content-between align-items-start">
                      <div className="font-mono fw-semibold" style={{ color: 'var(--neon-cyan)' }}>{hat.display_id || `#${hat.id}`}</div>
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
            ))
          )}
        </>
      )}
    </>
  );
}
