/**
 * Search as you type, and a search that survives leaving the page.
 *
 * The page used to search only on submit and kept everything in component
 * state, so Back from a result landed on an empty box. It now searches once
 * typing pauses, holds the last results on screen while the next arrive, and
 * mirrors the search into the URL. The stats page's color links also moved to
 * `?hex=` — `?color=` is the shared Color FILTER's key, and a hex there set
 * that filter to a value no hat has, filtering every ranked result away.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router';
import { renderWithProviders } from '../test/utils';
import { SearchPage, SEARCH_DEBOUNCE_MS } from './SearchPage';
import * as searchApi from '../api/search';
import type { ColorSearchResult, SearchResult } from '../types';

vi.mock('../api/search', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    searchHats: vi.fn(),
    searchHatsByColor: vi.fn(),
    getColorPalette: vi.fn(async () => [{ name: 'Blue', hex: '#0000ff' }]),
  };
});
vi.mock('../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getStyles: vi.fn(async () => []),
    getSizes: vi.fn(async () => []),
    getConditions: vi.fn(async () => []),
    getConstructions: vi.fn(async () => []),
  };
});
vi.mock('../api/rooms', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getRoomOptions: vi.fn(async () => []),
  };
});

const mocked = vi.mocked(searchApi);

function result(over: Partial<SearchResult> = {}): SearchResult {
  return {
    id: 1, display_id: 'A-001-01', case_display_id: 'A-001', photo_path: null, thumb_path: null,
    style: 'a_game', condition: 'new', size: 'classic', is_beanie: false,
    brand: 'melin', model_name: null, construction: null,
    colors: [{ color_name: 'ocean', general_color: 'blue', hex_value: '#0af', dominance_rank: 1 }],
    room_id: null, room_name: null,
    ...over,
  };
}

function colorResult(over: Partial<ColorSearchResult> = {}): ColorSearchResult {
  return { ...result(), matched_hex: '#0af', distance: 4, matched_rank: 1, ...over };
}

function LocationProbe() {
  const { search } = useLocation();
  return <div data-testid="search">{search}</div>;
}

function renderSearch(route = '/search') {
  return renderWithProviders(<><SearchPage /><LocationProbe /></>, { route });
}

function searchParams() {
  return new URLSearchParams(screen.getByTestId('search').textContent ?? '');
}

/** Long enough for the debounce to have fired, were it going to. */
const settle = () => new Promise(r => setTimeout(r, SEARCH_DEBOUNCE_MS + 150));

beforeEach(() => {
  vi.clearAllMocks();
  mocked.searchHats.mockResolvedValue([result()]);
  mocked.searchHatsByColor.mockResolvedValue([colorResult()]);
});

describe('SearchPage live search', () => {
  it('searches once typing pauses, not on every keystroke', async () => {
    const user = userEvent.setup();
    renderSearch();

    await user.type(screen.getByRole('searchbox', { name: 'Search hats' }), 'blue');

    expect(await screen.findByText('A-001-01')).toBeInTheDocument();
    expect(mocked.searchHats).toHaveBeenCalledTimes(1);
    expect(mocked.searchHats).toHaveBeenCalledWith('blue', false, undefined, 'major');
  });

  it('still searches immediately on submit', async () => {
    const user = userEvent.setup();
    renderSearch();

    await user.type(screen.getByRole('searchbox', { name: 'Search hats' }), 'blue{Enter}');

    expect(await screen.findByText('A-001-01')).toBeInTheDocument();
    await settle();
    // The debounce landing afterwards is the same search: no second request.
    expect(mocked.searchHats).toHaveBeenCalledTimes(1);
  });

  it('mirrors the search into the URL and restores it from there', async () => {
    const user = userEvent.setup();
    const first = renderSearch();
    await user.type(screen.getByRole('searchbox', { name: 'Search hats' }), 'blue');
    await waitFor(() => expect(searchParams().get('q')).toBe('blue'));
    first.unmount();

    // Back from a hat: the page remounts on the mirrored URL.
    renderSearch('/search?q=blue');
    expect(screen.getByRole('searchbox', { name: 'Search hats' })).toHaveValue('blue');
    expect(await screen.findByText('A-001-01')).toBeInTheDocument();
  });

  it('keeps the last results on screen while the next search loads', async () => {
    const user = userEvent.setup();
    renderSearch();
    const box = screen.getByRole('searchbox', { name: 'Search hats' });
    await user.type(box, 'blue');
    expect(await screen.findByText('A-001-01')).toBeInTheDocument();

    mocked.searchHats.mockReturnValue(new Promise(() => {}));
    await user.type(box, ' cap');
    await waitFor(() => expect(mocked.searchHats).toHaveBeenLastCalledWith('blue cap', false, undefined, 'major'));

    // Held, dimmed, and marked as updating — not blanked to a spinner.
    expect(screen.getByText('A-001-01')).toBeInTheDocument();
    expect(screen.getByText(/updating/i)).toBeInTheDocument();
    expect(screen.queryByText(/^searching…$/i)).toBeNull();
  });

  it('re-runs the search when exact color names is switched on', async () => {
    const user = userEvent.setup();
    renderSearch('/search?q=blue');
    await screen.findByText('A-001-01');

    const exact = screen.getByRole('switch', { name: /match exact color names/i });
    expect(exact).toHaveAttribute('aria-checked', 'false');
    await user.click(exact);

    expect(exact).toHaveAttribute('aria-checked', 'true');
    await waitFor(() => expect(mocked.searchHats).toHaveBeenLastCalledWith('blue', true, undefined, 'major'));
    await waitFor(() => expect(searchParams().get('exact')).toBe('1'));
  });

  it('runs a color search from ?hex= without filtering the results away', async () => {
    renderSearch('/search?hex=%23aabbcc');

    expect(await screen.findByText('A-001-01')).toBeInTheDocument();
    expect(mocked.searchHatsByColor).toHaveBeenCalledWith('#aabbcc', undefined);
    expect(screen.getByText(/1 of 1 result/)).toBeInTheDocument();
  });

  it('honors the old ?color=#hex link and rewrites it to ?hex=', async () => {
    // Before the fix this seeded the Color FILTER with "#aabbcc": the ranked
    // results arrived and every one was filtered out — "0 of 1 result".
    renderSearch('/search?color=%23aabbcc');

    expect(await screen.findByText('A-001-01')).toBeInTheDocument();
    expect(mocked.searchHatsByColor).toHaveBeenCalledWith('#aabbcc', undefined);
    await waitFor(() => expect(searchParams().get('hex')).toBe('#aabbcc'));
    expect(searchParams().get('color')).toBeNull();
  });

  it('keeps a picked swatch after the typing debounce has passed', async () => {
    // The debounce effect must not read the box emptied by a pick as "the
    // user cleared the search" and drop back out of the color results.
    const user = userEvent.setup();
    renderSearch();
    await user.type(screen.getByRole('searchbox', { name: 'Search hats' }), 'red');
    await waitFor(() => expect(mocked.searchHats).toHaveBeenCalledWith('red', false, undefined, 'major'));

    const swatch = await screen.findByRole('button', { name: 'Search hats near Blue' });
    await user.click(swatch);

    expect(screen.getByRole('searchbox', { name: 'Search hats' })).toHaveValue('');
    await waitFor(() => expect(mocked.searchHatsByColor).toHaveBeenCalledWith('#0000ff', undefined));
    await settle();
    expect(swatch).toHaveAttribute('aria-pressed', 'true');
    expect(searchParams().get('hex')).toBe('#0000ff');
    expect(searchParams().get('q')).toBeNull();
  });
});
