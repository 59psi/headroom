/**
 * A room shows what is in it, loose hats first.
 *
 * There was no room view at all before this: `/rooms` listed names with edit
 * and delete, and rooms weren't clickable. So the room-stored hats added in
 * 2.33 had nowhere to be seen — the Cases tab reaches a hat through its case,
 * and a hat on a shelf has no case to be reached through.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { Routes, Route } from 'react-router';
import { renderWithProviders } from '../test/utils';
import { caseFixture, hatFixture } from '../test/fixtures';
import { RoomDetailPage } from './RoomDetailPage';
import * as roomsApi from '../api/rooms';
import type { CaseRead, RoomDetail } from '../types';

vi.mock('../api/rooms', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getRoom: vi.fn()
  };
});

const mocked = vi.mocked(roomsApi);

function aCase(over: Partial<CaseRead> = {}): CaseRead {
  return caseFixture({
    room_name: 'Study', hat_count: 1, regular_count: 1,
    accepts_beanie: false, free_regular: 2, free_beanie: 0, ...over,
  });
}

function room(over: Partial<RoomDetail> = {}): RoomDetail {
  return {
    id: 1, name: 'Study', case_count: 0, loose_hat_count: 0, is_default: false,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    loose_hats: [], cases: [],
    ...over,
  };
}

function renderRoom(data: RoomDetail) {
  mocked.getRoom.mockResolvedValue(data);
  return renderWithProviders(
    <Routes><Route path="/rooms/:roomId" element={<RoomDetailPage />} /></Routes>,
    { route: '/rooms/1' },
  );
}

beforeEach(() => vi.clearAllMocks());

describe('RoomDetailPage', () => {
  it('lists the hats kept loose in the room', async () => {
    renderRoom(room({
      loose_hats: [hatFixture({ id: 7, model_name: 'Caddy Classic' })],
    }));

    expect(await screen.findByText('Caddy Classic')).toBeInTheDocument();
    // Specific: "No cases in this room" also contains "no case".
    expect(screen.getByText(/1 hat, no case/i)).toBeInTheDocument();
  });

  it('puts loose hats ABOVE the cases', async () => {
    // The ask, and the reason for it: a cased hat is findable three other
    // ways, a loose one is findable here and in search.
    const { container } = renderRoom(room({
      loose_hats: [hatFixture({ id: 7, model_name: 'On the shelf' })],
      cases: [aCase()],
    }));

    await screen.findByText('On the shelf');

    const headings = [...container.querySelectorAll('h2')].map(h => h.textContent);
    expect(headings).toEqual(['Out in this room', 'Cases']);
  });

  it('shows the cases too', async () => {
    renderRoom(room({ cases: [aCase({ display_id: 'A-042' })] }));
    expect(await screen.findByText('A-042')).toBeInTheDocument();
  });

  it('omits the loose section entirely when nothing is out', async () => {
    // An empty "Out in this room" header would imply a section you'd failed to
    // fill rather than a room whose hats are all cased.
    renderRoom(room({ cases: [aCase()] }));

    await screen.findByText('A-001');
    expect(screen.queryByText('Out in this room')).not.toBeInTheDocument();
  });

  it('says an empty room is empty, and why it might not be', async () => {
    renderRoom(room());
    expect(await screen.findByText(/This room is empty/)).toBeInTheDocument();
  });

  it('does not call the API for a non-numeric room id', async () => {
    mocked.getRoom.mockResolvedValue(room());
    renderWithProviders(
      <Routes><Route path="/rooms/:roomId" element={<RoomDetailPage />} /></Routes>,
      { route: '/rooms/nonsense' },
    );

    expect(await screen.findByText('Room not found')).toBeInTheDocument();
    expect(mocked.getRoom).not.toHaveBeenCalled();
  });
});
