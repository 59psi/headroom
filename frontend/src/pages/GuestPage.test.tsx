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

vi.mock('../api/guest', () => ({ getGuestCollection: vi.fn() }));

const mocked = vi.mocked(guestApi);

function collection(names: string[]) {
  return {
    label: 'The collection',
    hat_count: names.length,
    hats: names.map((model_name, i) => ({
      id: i + 1, display_id: null, brand: 'Melin', model_name,
      style: 'a_game', photo_url: null, colors: [], case: null, room: null,
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

    expect(mocked.getGuestCollection).toHaveBeenLastCalledWith('hydro');
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

    expect(mocked.getGuestCollection).toHaveBeenLastCalledWith('a&b c');
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
  });
});
