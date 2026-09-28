/**
 * Browsing without an account.
 *
 * The security properties live server-side (the projection, the off-by-default
 * switch, the 404) and are tested there. What matters here is that the page
 * asks the SERVER to search rather than filtering a fetched list — a
 * client-side filter would be a second, worse search that quietly stopped
 * matching what the owner's search matches.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../test/utils';
import { GuestPage } from './GuestPage';
import * as guestApi from '../api/guest';

vi.mock('../api/guest', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getGuestCollection: vi.fn()
  };
});

const mocked = vi.mocked(guestApi);

function collection(names: string[]) {
  return {
    label: 'The collection',
    hat_count: names.length,
    hats: names.map((model_name, i) => ({
      id: i + 1, display_id: null, brand: 'Melin', model_name,
      style: 'a_game', photo_url: null, thumb_url: null, colors: [], case: null, room: null,
    })),
  };
}

beforeEach(() => vi.clearAllMocks());

describe('GuestPage', () => {
  it('lists the collection', async () => {
    mocked.getGuestCollection.mockResolvedValue(collection(['Coronado', 'Odysea']));

    renderWithProviders(<GuestPage />);

    expect(await screen.findByText('Melin Coronado')).toBeInTheDocument();
    expect(screen.getByText('Melin Odysea')).toBeInTheDocument();
  });

  it('sends the search to the server, not a client-side filter', async () => {
    const user = userEvent.setup();
    mocked.getGuestCollection.mockResolvedValue(collection(['Coronado']));
    renderWithProviders(<GuestPage />);
    await screen.findByText('Melin Coronado');

    await user.type(screen.getByLabelText('Search the collection'), 'hydro');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    // Second arg is the color scope — which swatches a color term may match.
    expect(mocked.getGuestCollection).toHaveBeenLastCalledWith('hydro', 'major');
  });

  it('does not fire a request per keystroke', async () => {
    // A request per character is a lot of load to hand an unauthenticated
    // caller; only the submitted term goes to the server.
    const user = userEvent.setup();
    mocked.getGuestCollection.mockResolvedValue(collection(['Coronado']));
    renderWithProviders(<GuestPage />);
    await screen.findByText('Melin Coronado');
    const before = mocked.getGuestCollection.mock.calls.length;

    await user.type(screen.getByLabelText('Search the collection'), 'hydro');

    expect(mocked.getGuestCollection.mock.calls.length).toBe(before);
  });

  it('passes the raw term — the client escapes it', async () => {
    const user = userEvent.setup();
    mocked.getGuestCollection.mockResolvedValue(collection([]));
    renderWithProviders(<GuestPage />);

    await user.type(screen.getByLabelText('Search the collection'), 'a&b c');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    expect(mocked.getGuestCollection).toHaveBeenLastCalledWith('a&b c', 'major');
  });

  it('makes each hat openable', async () => {
    // "Where does this one live" is the question; a grid you cannot click
    // leaves it unanswered.
    mocked.getGuestCollection.mockResolvedValue(collection(['Coronado']));

    renderWithProviders(<GuestPage />);

    const tile = await screen.findByRole('link', { name: /Melin Coronado/ });
    expect(tile).toHaveAttribute('href', '/guest/hat/1');
  });

  it('lets you switch to matching accents only', async () => {
    // "Which of my hats has pink on it somewhere" is its own question, not the
    // leftovers of the default.
    const user = userEvent.setup();
    mocked.getGuestCollection.mockResolvedValue(collection(['Coronado']));
    renderWithProviders(<GuestPage />);
    await screen.findByText('Melin Coronado');

    await user.type(screen.getByLabelText('Search the collection'), 'pink');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    await user.click(await screen.findByRole('button', { name: 'Accents only' }));

    expect(mocked.getGuestCollection).toHaveBeenLastCalledWith('pink', 'accent');
  });

  it('offers a way back to signing in', async () => {
    mocked.getGuestCollection.mockResolvedValue(collection([]));
    renderWithProviders(<GuestPage />);
    expect(await screen.findByRole('link', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('says so plainly when guest browsing is unavailable', async () => {
    // The server 404s when the owner has it switched off.
    mocked.getGuestCollection.mockRejectedValue(new Error('Not found'));

    renderWithProviders(<GuestPage />);

    expect(await screen.findByText(/isn't available/i)).toBeInTheDocument();
    // …and still offers the way out.
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login');
  });

  it('holds the grid shape on first load instead of blanking the page', () => {
    mocked.getGuestCollection.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<GuestPage />);
    expect(screen.getByText('Loading the collection…')).toBeInTheDocument();
    // The search box is usable before the grid arrives.
    expect(screen.getByLabelText('Search the collection')).toBeInTheDocument();
  });

  it('keeps the last result on screen, marked stale, while a new search runs', async () => {
    // Each search is a new query key; without placeholder data every submit
    // blanked the grid to a spinner and back.
    const user = userEvent.setup();
    mocked.getGuestCollection.mockResolvedValueOnce(collection(['Coronado', 'Odysea']));
    renderWithProviders(<GuestPage />);
    await screen.findByText('Melin Coronado');

    let land!: (v: ReturnType<typeof collection>) => void;
    mocked.getGuestCollection.mockReturnValueOnce(new Promise(r => { land = r; }));
    await user.type(screen.getByLabelText('Search the collection'), 'hydro');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    // Still there, dimmed, and the count line says what is happening.
    expect(screen.getByText('Melin Coronado')).toBeInTheDocument();
    expect(await screen.findByText('Searching…')).toBeInTheDocument();
    expect(document.querySelector('.hr-results')).toHaveClass('is-stale');
    expect(screen.queryByText('Loading the collection…')).toBeNull();

    land(collection(['Hydro']));

    expect(await screen.findByText('Melin Hydro')).toBeInTheDocument();
    expect(screen.queryByText('Melin Coronado')).toBeNull();
    expect(screen.getByText(/1 hat matching “hydro”/)).toBeInTheDocument();
    expect(document.querySelector('.hr-results')).not.toHaveClass('is-stale');
  });
});
