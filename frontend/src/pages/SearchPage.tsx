import { useEffect, useState, useMemo } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { ErrorNote } from '../components/common/ErrorNote';
import { Link, useSearchParams } from 'react-router';
import { getColorPalette, searchHats, searchHatsByColor } from '../api/search';
import { ColorScopePicker, COLOR_SCOPES } from '../components/common/ColorScopePicker';
import { ColorSwatches } from '../components/common/ColorSwatch';
import { ConditionBadge } from '../components/common/ConditionBadge';
import { PageHeader } from '../components/ui/PageHeader';
import { Switch } from '../components/ui/Switch';
import { tileSrc } from '../lib/photo';
import { useDebouncedValue } from '../lib/useDebouncedValue';
import { useHatLabels } from '../lib/labels';
import {
  useHatFilters, HatFilterBar, FilterToggleButton, ActiveFilterChips, useMirrorToUrl,
  collectGeneralColors, matchesHatFilters,
} from '../components/hats/HatFilters';
import type { ColorSearchResult, SearchResult } from '../types';

/**
 * How long typing must pause before the search runs.
 *
 * Long enough that "blue a_game" is one request rather than eleven, short
 * enough that the results feel like they follow the typing. The search itself
 * is a local SQLite query over a few hundred rows; the pause is for the
 * network hop and for the list not to flicker under every keystroke.
 */
export const SEARCH_DEBOUNCE_MS = 350;

/**
 * How to describe the swatch a color search matched on, or '' for the hat's
 * main color (which needs no explanation).
 *
 * Derived from `matched_rank` rather than from the swatch's own `tier` string:
 * rank is assigned positionally by every writer on the server, while `tier`
 * comes from the client on the manual-edit path and can disagree with the
 * position it is stored at. Since rank is also what the server's ordering
 * penalty uses, deriving the label from it keeps the words and the order
 * telling the same story.
 */
export function matchedRankLabel(rank: number): string {
  if (rank <= 1) return '';
  return rank === 2 ? 'secondary' : 'accent';
}

/**
 * The hex a link asked to search by. `?hex=` is the current spelling; a hex in
 * `?color=` is the older one, still honored so a bookmarked stats link keeps
 * working. (`color` also names the shared Color FILTER, which holds palette
 * names — that clash is why the search moved to its own key.)
 */
function hexFromParams(params: URLSearchParams): string | null {
  const hex = params.get('hex');
  if (hex) return hex.startsWith('#') ? hex : `#${hex}`;
  const legacy = params.get('color');
  return legacy?.startsWith('#') ? legacy : null;
}

const SCOPE_VALUES: readonly string[] = COLOR_SCOPES.map(s => s.value);

function ResultsSkeleton() {
  return (
    <div className="hr-cp-list" role="status" aria-live="polite">
      <span className="visually-hidden">Searching…</span>
      {Array.from({ length: 3 }, (_, i) => (
        <div key={i} className="card hr-cp-row" aria-hidden="true">
          <div className="card-body hr-cp-row-body">
            <span className="hr-skeleton hr-cp-row-thumb hr-cp-skel-thumb hr-cp-skel-thumb-sm" />
            <div className="hr-cp-row-main hr-cp-skel-stack">
              <span className="hr-skeleton hr-skeleton-line hr-cp-skel-w35" />
              <span className="hr-skeleton hr-skeleton-line hr-cp-skel-w55" />
              <span className="hr-skeleton hr-skeleton-line hr-cp-skel-w75" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function ResultRow({ hat }: { hat: SearchResult | ColorSearchResult }) {
  const labels = useHatLabels();
  return (
    <Link to={`/hats/${hat.id}`} className="card hr-cp-row">
      <div className="card-body hr-cp-row-body">
        {hat.photo_path ? (
          <img src={tileSrc(hat)} alt="" className="hr-thumb hr-cp-row-thumb hr-cp-thumb-72" />
        ) : (
          <div className="hr-cp-row-thumb hr-cp-thumb-72 hr-cp-thumb-empty" aria-hidden="true" />
        )}
        <div className="hr-cp-row-main">
          <div className="hr-cp-row-top">
            <div className="hr-cp-row-id">{hat.display_id || `#${hat.id}`}</div>
            <ConditionBadge condition={hat.condition} />
          </div>
          {(hat.brand || hat.model_name) && (
            <div className="hr-cp-row-name">
              {[hat.brand, hat.model_name].filter(Boolean).join(' ')}
            </div>
          )}
          <div className="hr-cp-row-meta">
            {labels.style(hat.style)} · {labels.size(hat.size)}
            {(hat.case_display_id || hat.room_name) && (
              <> · {[hat.case_display_id && `Case ${hat.case_display_id}`, hat.room_name].filter(Boolean).join(' · ')}</>
            )}
          </div>
          <ColorSwatches colors={hat.colors} showLabels={false} />
          {'matched_hex' in hat && (
            <div className="hr-cp-match">
              matched
              <span className="hr-cp-dot hr-cp-dot-sm" style={{ background: hat.matched_hex }} aria-hidden="true" />
              <span className="font-mono">Δ{hat.distance.toFixed(0)}</span>
              {/* Without this, the ordering looks broken: a hat whose
                  ACCENT is exactly your color shows Δ0 and still sits
                  below a hat whose main color is Δ5, because the
                  server weighs a match by how much of the hat wears
                  it. The label is what makes that legible. */}
              {matchedRankLabel(hat.matched_rank) && (
                <span>· {matchedRankLabel(hat.matched_rank)}</span>
              )}
            </div>
          )}
        </div>
      </div>
    </Link>
  );
}

export function SearchPage() {
  // `?q=` and `?hex=` let other pages hand off a search — the stats page's
  // color bars link straight to the ranked results for that shade. Initial
  // value only; the controls own the state from then on, and
  // `useMirrorToUrl` below writes it back so Back from a hat returns here
  // with the same search rather than an empty box.
  const [searchParams] = useSearchParams();
  const initialQuery = searchParams.get('q') ?? '';
  const [query, setQuery] = useState(initialQuery);
  const [searchTerm, setSearchTerm] = useState(initialQuery);
  const [exactColors, setExactColors] = useState(() => searchParams.get('exact') === '1');
  // Which swatches a color term may match. Default is the hat's own
  // colors — a hat is not "pink" because its logo is.
  const [colorScope, setColorScope] = useState(() => {
    const s = searchParams.get('scope');
    return s && SCOPE_VALUES.includes(s) ? s : 'major';
  });
  const [colorHex, setColorHex] = useState<string | null>(() => hexFromParams(searchParams));
  const [pickerHex, setPickerHex] = useState(() => hexFromParams(searchParams) ?? '#8cb9e1');

  const hatFilters = useHatFilters();
  const { filters, activeCount: activeFilterCount, isOpen: filtersOpen, setIsOpen: setFiltersOpen } = hatFilters;

  // `...filters` carries `color` — the Color FILTER, never the hex (see
  // `hexFromParams`) — so a legacy `?color=#…` is rewritten to `?hex=` on
  // arrival rather than lingering to be misread.
  useMirrorToUrl({
    ...filters,
    q: searchTerm,
    hex: colorHex ?? '',
    exact: exactColors ? '1' : '',
    scope: colorScope === 'major' ? '' : colorScope,
  });

  // Search as you type. The form still submits (Enter, the button) for an
  // immediate search; this runs the same search once typing pauses.
  const settledQuery = useDebouncedValue(query, SEARCH_DEBOUNCE_MS);
  useEffect(() => {
    const term = settledQuery.trim();
    // Already showing it (a submit got there first, or nothing changed).
    if (term === searchTerm) return;
    // An emptied box during a color search is the color pick clearing it,
    // not a request to leave the color results.
    if (!term && colorHex) return;
    if (term) setColorHex(null);
    setSearchTerm(term);
    // Keyed on the settled text alone: re-running when `searchTerm` or
    // `colorHex` change would undo a color pick the moment it happens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settledQuery]);

  const paletteQ = useQuery({ queryKey: ['meta', 'colors'], queryFn: getColorPalette });

  // Room is applied server-side here — the API returns an already-filtered set,
  // which is why it isn't part of `matchesHatFilters`.
  const roomIdParam = filters.room ? Number(filters.room) : undefined;

  // `keepPreviousData`: while the next search is in flight the last results
  // stay on screen (dimmed) instead of the list blanking to a spinner on
  // every pause in typing.
  const textQ = useQuery({
    queryKey: ['search', searchTerm, exactColors, roomIdParam, colorScope],
    queryFn: () => searchHats(searchTerm, exactColors, roomIdParam, colorScope),
    enabled: !colorHex && searchTerm.length > 0,
    placeholderData: keepPreviousData,
  });

  const colorQ = useQuery({
    queryKey: ['search', 'color', colorHex, roomIdParam],
    queryFn: () => searchHatsByColor(colorHex!, roomIdParam),
    enabled: !!colorHex,
    placeholderData: keepPreviousData,
  });

  const activeQ = colorHex ? colorQ : textQ;
  const data: SearchResult[] | ColorSearchResult[] | undefined = activeQ.data;
  const isLoading = activeQ.isLoading;
  const isStale = activeQ.isPlaceholderData;
  const error = activeQ.error;
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

  const showFilterControls = !!data && (data.length > 0 || activeFilterCount > 0);

  return (
    <>
      <PageHeader
        title="Search"
        // Lives here rather than in the nav: it is an occasional housekeeping
        // task, and searching is the frame of mind you're already in when you
        // go looking for a hat you think you saw twice.
        actions={
          <Link to="/duplicates" className="btn btn-outline-secondary btn-sm">
            Find duplicates
          </Link>
        }
      />

      <form onSubmit={handleSubmit} className="hr-cp-search" role="search">
        <div className="hr-field-row">
          <input
            type="search"
            aria-label="Search hats"
            className="form-control"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Color, brand, style, size, room…"
            enterKeyHint="search"
          />
          <button type="submit" className="btn btn-primary">Search</button>
        </div>

        {/* Which NAME a color term matches, and which SWATCH — adjacent
            questions, so they sit together under the box. Both re-run the
            search the moment they change. */}
        <div className="hr-cp-search-opts">
          <div className="hr-cp-inline-switch">
            <Switch
              id="exactColors"
              checked={exactColors}
              onChange={setExactColors}
              label="Match exact color names"
              hint={<>e.g. <span className="font-mono">darkslategray</span></>}
            />
          </div>
          <div className="hr-cp-scope">
            <span className="hr-cp-scope-label">Color terms match</span>
            <ColorScopePicker value={colorScope} onChange={setColorScope} />
          </div>
        </div>
      </form>

      <section className="hr-cp-palette" aria-label="Search by color">
        {/* A sentence, so it is set as one — not in the all-caps microtype
            of `.hr-eyebrow`, which is for two-word group labels. */}
        <p className="hr-cp-palette-hint">…or tap a color to find the closest hats</p>
        <div className="hr-cp-swatches">
          {paletteQ.data?.map(c => (
            <button
              key={c.hex}
              type="button"
              className="hr-cp-swatch"
              title={c.name}
              aria-label={`Search hats near ${c.name}`}
              aria-pressed={colorHex === c.hex}
              onClick={() => pickColor(c.hex)}
              style={{ background: c.hex }}
            />
          ))}
          <label className="hr-cp-any-color">
            <input
              type="color"
              value={pickerHex}
              onChange={e => setPickerHex(e.target.value)}
              onBlur={() => pickColor(pickerHex)}
              aria-label="Pick any color"
            />
            any color
          </label>
        </div>
      </section>

      {!hasQuery && (
        <div className="hr-cp-empty hr-cp-empty-quiet">
          <div className="hr-cp-empty-title">Search across every hat</div>
          <p>By name, brand, color, style, condition, size, or room.</p>
          <p className="small mb-0">
            Every word must match: <span className="font-mono">blue a_game</span> · or tap a swatch above
          </p>
        </div>
      )}

      {hasQuery && isLoading && <ResultsSkeleton />}
      <ErrorNote of={{ isError: !!error, error }} what="Search failed" />
      <ErrorNote of={paletteQ} what="Could not load the color palette" />

      {data && hasQuery && (
        <>
          <div className="hr-cp-results-head">
            <div className="hr-cp-results-count" aria-live="polite">
              {filteredData.length} of {data.length} result{data.length !== 1 ? 's' : ''}{' '}
              {colorHex ? (
                <>
                  nearest to
                  <span className="hr-cp-dot" style={{ background: colorHex }} aria-hidden="true" />
                </>
              ) : (
                <>for &ldquo;{searchTerm}&rdquo;</>
              )}
              {activeQ.isFetching && <span className="hr-cp-updating">Updating…</span>}
            </div>
            {showFilterControls && (
              <FilterToggleButton
                activeCount={activeFilterCount}
                isOpen={filtersOpen}
                onToggle={setFiltersOpen}
              />
            )}
          </div>

          {showFilterControls && (filtersOpen
            ? <HatFilterBar state={hatFilters} colors={availableColors} />
            : <ActiveFilterChips state={hatFilters} />)}

          <div className={`hr-cp-results${isStale ? ' is-stale' : ''}`} aria-busy={isStale || undefined}>
            {filteredData.length === 0 ? (
              <div className="hr-cp-empty">
                {/* A color search returning nothing now means "nothing close
                    enough", not "no hats" — before the distance cutoff it
                    always filled to the limit, so empty was impossible and
                    "No hats found" was never wrong. It would be now. */}
                <div className="hr-cp-empty-title">
                  {activeFilterCount > 0
                    ? 'No results match your filters'
                    : colorHex
                      ? 'No hats are close to that color'
                      : 'No hats found'}
                </div>
                {colorHex && activeFilterCount === 0 && (
                  <p className="mb-0">
                    Only genuinely similar shades are shown. Try a nearby color,
                    or a palette swatch above.
                  </p>
                )}
                {!colorHex && activeFilterCount === 0 && (
                  <p className="mb-0">Every word has to match — try fewer words.</p>
                )}
                {activeFilterCount > 0 && (
                  <div className="hr-cp-empty-actions">
                    <button type="button" className="btn btn-outline-secondary" onClick={hatFilters.clear}>
                      Show all results
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div className="hr-cp-list">
                {filteredData.map(hat => <ResultRow key={hat.id} hat={hat} />)}
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
