/**
 * New case: files it in whichever room carries the default flag (never a
 * hardcoded id), submits on Enter like any form, and opens the case it made.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route, useParams } from 'react-router';
import { renderWithProviders } from '../test/utils';
import { caseFixture } from '../test/fixtures';
import { NewCasePage } from './NewCasePage';
import * as casesApi from '../api/cases';
import * as roomsApi from '../api/rooms';
import type { RoomRead } from '../types';

vi.mock('../api/cases', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), createCase: vi.fn() };
});
vi.mock('../api/rooms', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), listRooms: vi.fn() };
});

const cases = vi.mocked(casesApi);
const rooms = vi.mocked(roomsApi);

function aRoom(id: number, name: string, isDefault = false): RoomRead {
  return {
    id, name, case_count: 0, loose_hat_count: 0, is_default: isDefault,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  };
}

function CaseLanding() {
  const { displayId } = useParams();
  return <p>{`Landed on ${displayId}`}</p>;
}

function renderNew() {
  return renderWithProviders(
    <Routes>
      <Route path="/cases/new" element={<NewCasePage />} />
      <Route path="/cases/:displayId" element={<CaseLanding />} />
    </Routes>,
    { route: '/cases/new' },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // The default is the SECOND room: a hardcoded 1 would pick the wrong one.
  rooms.listRooms.mockResolvedValue([aRoom(1, 'Main'), aRoom(2, 'Den', true)]);
  cases.createCase.mockResolvedValue(caseFixture({ display_id: 'A-005' }));
});

describe('NewCasePage', () => {
  it('preselects the default room, creates on Enter, and opens the new case', async () => {
    const user = userEvent.setup();
    renderNew();

    await screen.findByRole('option', { name: 'Den' });
    expect(screen.getByRole('combobox', { name: 'Room' })).toHaveValue('2');

    await user.type(screen.getByRole('spinbutton', { name: 'Capacity (hats)' }), '4{Enter}');

    expect(cases.createCase).toHaveBeenCalledWith('archive', 2, 4);
    expect(await screen.findByText('Landed on A-005')).toBeInTheDocument();
    expect(await screen.findByText('Case A-005 created')).toBeInTheDocument();
  });

  it('keeps a failed create on the form and says why', async () => {
    cases.createCase.mockRejectedValueOnce(new Error('Room 2 not found'));
    const user = userEvent.setup();
    renderNew();

    await screen.findByRole('option', { name: 'Den' });
    await user.click(screen.getByRole('button', { name: 'Create case' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not create the case — Room 2 not found');
    expect(screen.getByRole('heading', { level: 1, name: 'New case' })).toBeInTheDocument();
  });
});
