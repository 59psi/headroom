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
import { Routes, Route } from 'react-router';
import { renderWithProviders } from '../test/utils';
import { SharePage } from './SharePage';
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
      style: 'a_game', photo_url: null, thumb_url: null,
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
    mocked.getSharedCollection.mockRejectedValue(new Error('Not found'));
    render();
    expect(await screen.findByText('This share link is invalid, expired, or was revoked.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: "This link isn't working" })).toBeInTheDocument();
  });

  it('shows the brand in the header, not as the page heading', async () => {
    mocked.getSharedCollection.mockResolvedValue(collection([]));
    render();
    await screen.findByRole('heading', { name: 'Summer rotation' });
    expect(screen.getByRole('banner')).toHaveTextContent('Headroom');
    expect(screen.getByText('Nothing to show.')).toBeInTheDocument();
  });
});
