import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getColorPalette, searchHats, searchHatsByColor } from '../api/search';
import { ColorSwatches } from '../components/common/ColorSwatch';
import { ConditionBadge } from '../components/common/ConditionBadge';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import {
  useHatFilters, HatFilterBar, FilterToggleButton,
  collectGeneralColors, matchesHatFilters,
} from '../components/hats/HatFilters';
import type { ColorSearchResult, SearchResult } from '../types';

export function SearchPage() {
  const [query, setQuery] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [exactColors, setExactColors] = useState(false);
  const [colorHex, setColorHex] = useState<string | null>(null);
  const [pickerHex, setPickerHex] = useState('#8cb9e1');

  const hatFilters = useHatFilters();
  const { filters, activeCount: activeFilterCount, isOpen: filtersOpen, setIsOpen: setFiltersOpen } = hatFilters;

  const paletteQ = useQuery({ queryKey: ['meta', 'colors'], queryFn: getColorPalette });

  // Room is applied server-side here — the API returns an already-filtered set,
  // which is why it isn't part of `matchesHatFilters`.
  const roomIdParam = filters.room ? Number(filters.room) : undefined;

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

  const availableColors = useMemo(() => collectGeneralColors(data), [data]);

  const filteredData = useMemo(
    () => (data ?? []).filter(h => matchesHatFilters(h, filters)),
    [data, filters]
  );

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
              <FilterToggleButton
                activeCount={activeFilterCount}
                isOpen={filtersOpen}
                onToggle={setFiltersOpen}
              />
            )}
          </div>

          {filtersOpen && data.length > 0 && (
            <HatFilterBar state={hatFilters} colors={availableColors} />
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
