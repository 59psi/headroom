/**
 * The Hats tab: instant filters that survive leaving the page.
 *
 * Filters lived only in component state, so opening a hat and pressing Back
 * rebuilt the list unfiltered. They are mirrored into the URL now, and these
 * pin both directions — seeded FROM the URL on arrival, written BACK as they
 * change — plus the pieces that make a filtered list legible: the live count,
 * the removable chips, and an empty state with a way out.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation, useNavigationType } from 'react-router';
import { renderWithProviders } from '../test/utils';
import { hatFixture } from '../test/fixtures';
import { HatsPage } from './HatsPage';
import * as hatsApi from '../api/hats';

vi.mock('../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    listAllHats: vi.fn(),
    getStyles: vi.fn(async () => [
      { value: 'a_game', label: 'A-Game', is_beanie: false },
      { value: 'odysea', label: 'Odysea', is_beanie: false },
    ]),
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

const mocked = vi.mocked(hatsApi);

/** Renders the current query string, so a test can read what was mirrored. */
function LocationProbe() {
  const { search } = useLocation();
  // A plain div: an <output> has an implicit `status` role and would be
  // mistaken for the loading skeleton's.
  return <div data-testid="search">{search}</div>;
}

function renderHats(route = '/hats') {
  return renderWithProviders(<><HatsPage /><LocationProbe /></>, { route });
}

const HATS = [
  hatFixture({ id: 1, display_id: 'A-001-01', style: 'a_game', brand: 'melin' }),
  hatFixture({ id: 2, display_id: 'A-001-02', style: 'odysea', brand: 'melin' }),
  // Loose: no case, no room — "Unassigned". No shelf id, so its gallery tile
  // goes by its model, "Loose One" (`hatName`), as its list row does.
  hatFixture({ id: 3, display_id: null, case_display_id: null, model_name: 'Loose One', style: 'odysea', brand: 'Other' }),
];

function searchParams() {
  return new URLSearchParams(screen.getByTestId('search').textContent ?? '');
}

/**
 * An in-memory `Storage`. Under this Node the test environment's
 * `localStorage` is Node's own, which is undefined without a backing file —
 * the page survives that (see the private-mode test), but a test of the
 * remembered choice needs somewhere for it to be remembered.
 */
function memoryStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() { return m.size; },
    clear: () => m.clear(),
    getItem: k => m.get(k) ?? null,
    key: i => [...m.keys()][i] ?? null,
    removeItem: k => { m.delete(k); },
    setItem: (k, v) => { m.set(k, String(v)); },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('localStorage', memoryStorage());
  mocked.listAllHats.mockResolvedValue(HATS);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('HatsPage', () => {
  it('shows skeleton tiles while loading, never the empty state', async () => {
    let resolve!: (v: typeof HATS) => void;
    mocked.listAllHats.mockReturnValue(new Promise(r => { resolve = r; }));

    renderHats();

    expect(screen.getByRole('status')).toHaveTextContent(/loading hats/i);
    expect(screen.queryByText(/no hats yet/i)).toBeNull();

    resolve(HATS);
    expect(await screen.findByText('A-001-01')).toBeInTheDocument();
    expect(screen.queryByText(/loading hats/i)).toBeNull();
  });

  it('offers a first hat only when the collection really is empty', async () => {
    mocked.listAllHats.mockResolvedValue([]);
    renderHats();

    expect(await screen.findByRole('link', { name: /add first hat/i })).toHaveAttribute('href', '/hats/new');
    // The header's import link, and the empty state's own.
    expect(screen.getAllByRole('link', { name: /bulk import/i })).toHaveLength(2);
  });

  it('seeds filters from the URL and names them as removable chips', async () => {
    const user = userEvent.setup();
    renderHats('/hats?style=odysea&brand=melin');

    // Only #2 is an Odysea by melin.
    expect(await screen.findByText('A-001-02')).toBeInTheDocument();
    expect(screen.queryByText('A-001-01')).toBeNull();
    expect(screen.queryByText('Loose One')).toBeNull();
    expect(screen.getByText('1 of 3')).toBeInTheDocument();

    // The chip uses the option's label once the options load, not the slug.
    const chip = await screen.findByRole('button', { name: 'Remove filter Style: Odysea' });
    await user.click(chip);

    // Style gone, brand still applied: both melin hats.
    expect(await screen.findByText('A-001-01')).toBeInTheDocument();
    expect(screen.getByText('A-001-02')).toBeInTheDocument();
    expect(screen.queryByText('Loose One')).toBeNull();
    await waitFor(() => expect(searchParams().get('style')).toBeNull());
    expect(searchParams().get('brand')).toBe('melin');
  });

  it('mirrors a placement chip into the URL and back out again', async () => {
    const user = userEvent.setup();
    renderHats();
    await screen.findByText('A-001-01');

    const chips = screen.getByRole('group', { name: /where the hat is kept/i });
    await user.click(within(chips).getByRole('button', { name: /unassigned/i }));

    expect(within(chips).getByRole('button', { name: /unassigned/i })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Loose One')).toBeInTheDocument();
    expect(screen.queryByText('A-001-01')).toBeNull();
    await waitFor(() => expect(searchParams().get('placement')).toBe('none'));

    await user.click(within(chips).getByRole('button', { name: 'All' }));
    await waitFor(() => expect(searchParams().get('placement')).toBeNull());
    expect(screen.getByText('A-001-01')).toBeInTheDocument();
  });

  it('writes filters with a replace, never a history entry per change', async () => {
    // A push per filter would make Back walk through every intermediate
    // filter state before it left the page.
    function NavTypeProbe() {
      return <div data-testid="nav-type">{useNavigationType()}</div>;
    }
    const user = userEvent.setup();
    renderWithProviders(<><HatsPage /><LocationProbe /><NavTypeProbe /></>, { route: '/hats' });
    await screen.findByText('A-001-01');

    await user.click(screen.getByRole('button', { name: /unassigned/i }));

    await waitFor(() => expect(searchParams().get('placement')).toBe('none'));
    expect(screen.getByTestId('nav-type')).toHaveTextContent('REPLACE');
  });

  it('keeps a query string it does not own when mirroring', async () => {
    // One page, one writer — but a key someone else put there (a campaign
    // tag, a future param) must survive the rewrite.
    const user = userEvent.setup();
    renderHats('/hats?ref=stats');
    await screen.findByText('A-001-01');

    await user.click(screen.getByRole('button', { name: /unassigned/i }));

    await waitFor(() => expect(searchParams().get('placement')).toBe('none'));
    expect(searchParams().get('ref')).toBe('stats');
  });

  it('shows a way out when filters hide everything', async () => {
    const user = userEvent.setup();
    renderHats('/hats?brand=nobody');

    expect(await screen.findByText(/no hats match these filters/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /show all hats/i }));

    expect(await screen.findByText('A-001-01')).toBeInTheDocument();
    await waitFor(() => expect(searchParams().get('brand')).toBeNull());
  });

  it('remembers list or gallery per device', async () => {
    const user = userEvent.setup();
    const first = renderHats();
    await screen.findByText('A-001-01');

    expect(screen.getByRole('button', { name: 'Gallery view' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'List view' }));
    expect(screen.getByRole('button', { name: 'List view' })).toHaveAttribute('aria-pressed', 'true');
    expect(window.localStorage.getItem('headroom.hats.view')).toBe('list');

    first.unmount();
    renderHats();
    await screen.findByText('A-001-01');
    expect(screen.getByRole('button', { name: 'List view' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('still renders when storage throws (private mode)', async () => {
    const denied = () => { throw new DOMException('denied', 'SecurityError'); };
    vi.stubGlobal('localStorage', { ...memoryStorage(), getItem: denied, setItem: denied });
    const user = userEvent.setup();

    renderHats();
    await screen.findByText('A-001-01');
    // Default view, and switching still works — for this visit.
    expect(screen.getByRole('button', { name: 'Gallery view' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'List view' }));
    expect(screen.getByRole('button', { name: 'List view' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('retries a failed load in place', async () => {
    const user = userEvent.setup();
    mocked.listAllHats.mockRejectedValueOnce(new Error('500'));
    renderHats();

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn.t load your hats/i);
    mocked.listAllHats.mockResolvedValue(HATS);
    await user.click(screen.getByRole('button', { name: /try again/i }));

    expect(await screen.findByText('A-001-01')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('ties the Brand label to its select, so tapping the word focuses it', async () => {
    const user = userEvent.setup();
    renderHats();
    await screen.findByText('A-001-01');
    await user.click(screen.getByRole('button', { name: /filters/i }));

    const label = await screen.findByText('Brand', { selector: 'label' });
    const select = screen.getByRole('combobox', { name: 'Brand' });
    expect(label).toHaveAttribute('for', select.id);
    expect(select).not.toHaveAttribute('aria-label');
    await user.click(label);
    expect(select).toHaveFocus();
  });
});
