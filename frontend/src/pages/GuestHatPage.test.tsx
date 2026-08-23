/**
 * One hat, as a guest sees it.
 *
 * The page renders only what `SharedHat` carries — so what's worth pinning is
 * that "where it lives" is actually present (the reason a guest opens a hat at
 * all), and that a caseless hat still reports its room.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { Routes, Route } from 'react-router';
import { renderWithProviders } from '../test/utils';
import { GuestHatPage } from './GuestHatPage';
import * as guestApi from '../api/guest';
import type { SharedHat } from '../types';

vi.mock('../api/guest', () => ({ getGuestHat: vi.fn() }));

const mocked = vi.mocked(guestApi);

function hat(over: Partial<SharedHat> = {}): SharedHat {
  return {
    id: 7, display_id: 'A-001-01', brand: 'Melin', model_name: 'Coronado',
    style: 'a_game', photo_url: null, colors: [], case: 'A-001', room: 'Study',
    ...over,
  };
}

function render(data: SharedHat | Error, id: string | number = 7) {
  if (data instanceof Error) mocked.getGuestHat.mockRejectedValue(data);
  else mocked.getGuestHat.mockResolvedValue(data);
  return renderWithProviders(
    <Routes><Route path="/guest/hat/:hatId" element={<GuestHatPage />} /></Routes>,
    { route: `/guest/hat/${id}` },
  );
}

beforeEach(() => vi.clearAllMocks());

describe('GuestHatPage', () => {
  it('names the hat', async () => {
    render(hat());
    expect(await screen.findByRole('heading', { name: 'Melin Coronado' })).toBeInTheDocument();
  });

  it('shows where it lives — the reason a guest opens a hat', async () => {
    render(hat({ room: 'Study', case: 'A-001' }));

    expect(await screen.findByText('Where it lives')).toBeInTheDocument();
    expect(screen.getByText('Study')).toBeInTheDocument();
    expect(screen.getByText('A-001')).toBeInTheDocument();
  });

  it('says so plainly when a hat is in a room but no case', async () => {
    render(hat({ case: null, room: 'Shelf' }));

    expect(await screen.findByText('Not in a case')).toBeInTheDocument();
    expect(screen.getByText('Shelf')).toBeInTheDocument();
  });

  it('offers a way back to the collection', async () => {
    render(hat());
    expect(await screen.findByRole('link', { name: '← Collection' })).toBeInTheDocument();
  });

  it('handles a hat that is not available', async () => {
    render(new Error('Not found'));
    expect(await screen.findByText(/isn't available/i)).toBeInTheDocument();
  });

  it('does not call the API for a non-numeric id', async () => {
    render(hat(), 'nonsense');
    expect(await screen.findByText(/isn't available/i)).toBeInTheDocument();
    expect(mocked.getGuestHat).not.toHaveBeenCalled();
  });
});
