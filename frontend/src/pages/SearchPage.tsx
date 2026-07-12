import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getColorPalette, searchHats, searchHatsByColor } from '../api/search';
import { getStyles, getSizes, getConditions } from '../api/hats';
import { getRoomOptions } from '../api/rooms';
import { ColorSwatches } from '../components/common/ColorSwatch';
import { ConditionBadge } from '../components/common/ConditionBadge';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import type { ColorSearchResult, SearchResult } from '../types';

export function SearchPage() {
  const [query, setQuery] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [exactColors, setExactColors] = useState(false);
  const [colorHex, setColorHex] = useState<string | null>(null);
  const [pickerHex, setPickerHex] = useState('#8cb9e1');

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
  const paletteQ = useQuery({ queryKey: ['meta', 'colors'], queryFn: getColorPalette });

  const roomIdParam = filterRoom ? Number(filterRoom) : undefined;

  const textQ = useQuery({
    queryKey: ['search', searchTerm, exactColors, roomIdParam],
    queryFn: () => searchHats(searchTerm, exactColors, roomIdParam),
    enabled: !colorHex && searchTerm.length > 0,
  });

  const colorQ = useQuery({
    queryKey: ['search', 'color', colorHex, roomIdParam],
    queryFn: () => searchHatsByColor(colorHex!, roomIdParam),
    enabled: !!colorHex,
  });

  const data: SearchResult[] | ColorSearchResult[] | undefined = colorHex ? colorQ.data : textQ.data;
  const isLoading = colorHex ? colorQ.isLoading : textQ.isLoading;
  const error = colorHex ? colorQ.error : textQ.error;
  const hasQuery = !!colorHex || searchTerm.length > 0;

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
    setColorHex(null);
    setSearchTerm(query.trim());
  }

  function pickColor(hex: string) {
    setSearchTerm('');
    setQuery('');
    setColorHex(prev => (prev === hex ? null : hex));
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

      <div className="mb-3">
        <div className="text-secondary small mb-2">…or tap a color to find the closest hats:</div>
        <div className="d-flex flex-wrap gap-2 align-items-center">
          {paletteQ.data?.map(c => (
            <button
              key={c.hex}
              type="button"
              title={c.name}
              aria-label={`Search hats near ${c.name}`}
              onClick={() => pickColor(c.hex)}
              style={{
                width: 34, height: 34, borderRadius: '50%', background: c.hex,
                border: colorHex === c.hex ? '3px solid var(--neon-cyan)' : '2px solid rgba(255,255,255,0.25)',
                cursor: 'pointer', padding: 0,
              }}
            />
          ))}
          <label
            className="d-inline-flex align-items-center gap-1 small text-secondary"
            style={{ cursor: 'pointer' }}
          >
            <input
              type="color"
              value={pickerHex}
              onChange={e => setPickerHex(e.target.value)}
              onBlur={() => pickColor(pickerHex)}
              style={{ width: 34, height: 34, padding: 0, border: 'none', background: 'transparent', cursor: 'pointer' }}
              aria-label="Pick any color"
            />
            any color
          </label>
        </div>
      </div>

      {!hasQuery && (
        <div className="text-center py-5 text-secondary">
          <p>Search across every hat by name, brand, color, style, condition, size, or room</p>
          <p className="small">Multi-term AND: <span className="font-mono">blue a_game</span> · or tap a swatch above</p>
        </div>
      )}

      {isLoading && <LoadingSpinner label="Searching" />}
      {error && <div className="alert alert-danger">{String(error)}</div>}

      {data && hasQuery && (
        <>
          <div className="d-flex justify-content-between align-items-center mb-3 gap-2 flex-wrap">
            <div className="text-secondary small font-mono d-flex align-items-center gap-2">
              {filteredData.length} of {data.length} result{data.length !== 1 ? 's' : ''}{' '}
              {colorHex ? (
                <>
                  nearest to
                  <span style={{
                    display: 'inline-block', width: 16, height: 16, borderRadius: '50%',
                    background: colorHex, border: '1px solid rgba(255,255,255,0.4)', verticalAlign: 'middle',
                  }} />
                </>
              ) : (
                <>for "{searchTerm}"</>
              )}
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
                    {(hat.brand || hat.model_name) && (
                      <div className="small fw-semibold" style={{ marginTop: 2 }}>
                        {[hat.brand, hat.model_name].filter(Boolean).join(' ')}
                      </div>
                    )}
                    <div className="text-muted small mb-1" style={{ marginTop: 4 }}>
                      {hat.style.replace(/_/g, ' ')} · {hat.size.replace(/_/g, ' ')}
                      {(hat.case_display_id || hat.room_name) && (
                        <> · 📍 {[hat.case_display_id && `Case ${hat.case_display_id}`, hat.room_name].filter(Boolean).join(' · ')}</>
                      )}
                    </div>
                    <ColorSwatches colors={hat.colors} showLabels={false} />
                    {'matched_hex' in hat && (
                      <div className="text-muted small d-flex align-items-center gap-1" style={{ marginTop: 4 }}>
                        matched
                        <span style={{
                          display: 'inline-block', width: 12, height: 12, borderRadius: '50%',
                          background: (hat as ColorSearchResult).matched_hex,
                          border: '1px solid rgba(255,255,255,0.4)',
                        }} />
                        <span className="font-mono">Δ{(hat as ColorSearchResult).distance.toFixed(0)}</span>
                      </div>
                    )}
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
