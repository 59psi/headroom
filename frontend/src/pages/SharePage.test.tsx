/**
 * The public, read-only collection behind a share link.
 *
 * What is pinned: the link's label and count are shown, tiles are NOT links
 * (a share viewer has no detail route to go to), a dead link says so in
 * words, and the first load holds the grid's shape rather than blanking the
 * page.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router';
import { renderWithProviders } from '../test/utils';
import { SharePage } from './SharePage';
import { ApiError } from '../api/client';
import * as shareApi from '../api/share';
import type { SharedCollection } from '../types';

vi.mock('../api/share', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getSharedCollection: vi.fn(),
  };
});

const mocked = vi.mocked(shareApi);

function collection(names: string[], label = 'Summer rotation'): SharedCollection {
  return {
    label,
    hat_count: names.length,
    hats: names.map((model_name, i) => ({
      id: i + 1, display_id: null, brand: 'Melin', model_name,
      style: 'a_game', style_label: 'A-Game', photo_url: null, thumb_url: null,
      colors: [{ name: 'Navy', hex: '#001f3f' }], case: null, room: null,
    })),
  };
}

function render(token = 'tok123') {
  return renderWithProviders(
    <Routes><Route path="/share/:token" element={<SharePage />} /></Routes>,
    { route: `/share/${token}` },
  );
}

beforeEach(() => vi.clearAllMocks());

describe('SharePage', () => {
  it('shows the link label, the count and the hats', async () => {
    mocked.getSharedCollection.mockResolvedValue(collection(['Coronado', 'Odysea']));
    render();

    expect(await screen.findByRole('heading', { name: 'Summer rotation' })).toBeInTheDocument();
    expect(screen.getByText(/2 hats · shared via Headroom/)).toBeInTheDocument();
    expect(screen.getByText('Melin Coronado')).toBeInTheDocument();
    expect(mocked.getSharedCollection).toHaveBeenCalledWith('tok123');
  });

  it('names an unidentified hat by its style, in the server’s words', async () => {
    const shared = collection(['x']);
    shared.hats[0] = { ...shared.hats[0], brand: null, model_name: null };
    mocked.getSharedCollection.mockResolvedValue(shared);
    render();
    expect(await screen.findByText('A-Game')).toBeInTheDocument();
    expect(screen.queryByText('A Game')).toBeNull();
  });

  it('does not make tiles look tappable — there is nowhere to go', async () => {
    mocked.getSharedCollection.mockResolvedValue(collection(['Coronado']));
    render();
    await screen.findByText('Melin Coronado');
    expect(screen.queryByRole('link', { name: /Coronado/ })).toBeNull();
  });

  it('holds the grid shape while loading, with one status message', () => {
    mocked.getSharedCollection.mockReturnValue(new Promise(() => {}));
    render();
    expect(screen.getAllByRole('status')).toHaveLength(1);
    expect(screen.getByText('Loading the collection…')).toBeInTheDocument();
  });

  it('says so in words when the link is dead', async () => {
    mocked.getSharedCollection.mockRejectedValue(new ApiError('Not found', 404));
    render();
    expect(await screen.findByText('This share link is invalid, expired, or was revoked.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: "This link isn't working" })).toBeInTheDocument();
  });

  it('does not call a good link revoked when the server fails — and retries', async () => {
    const user = userEvent.setup();
    mocked.getSharedCollection.mockRejectedValue(new ApiError('database is locked', 500));
    render();

    expect(await screen.findByRole('heading', { name: 'Couldn’t load this right now' })).toBeInTheDocument();
    expect(screen.getByText(/database is locked/)).toBeInTheDocument();
    expect(screen.queryByText(/revoked/)).toBeNull();

    mocked.getSharedCollection.mockResolvedValue(collection(['Coronado']));
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'Summer rotation' })).toBeInTheDocument();
  });

  it('shows the brand in the header, not as the page heading', async () => {
    mocked.getSharedCollection.mockResolvedValue(collection([]));
    render();
    await screen.findByRole('heading', { name: 'Summer rotation' });
    expect(screen.getByRole('banner')).toHaveTextContent('Headroom');
    expect(screen.getByText('Nothing to show.')).toBeInTheDocument();
  });
});
