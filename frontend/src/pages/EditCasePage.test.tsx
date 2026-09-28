/**
 * Saving a case lands on the case — under the number the SERVER gave it.
 *
 * Changing a case's type renumbers it (`case_service.update_case`: A-001
 * becomes the next D-###). The form navigated to the id in its own URL, so a
 * successful type change ended on "Case not found". It now follows the id the
 * save returned, and warns before the save that the number (and every tag
 * written for it) is about to change.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { focusManager } from '@tanstack/react-query';
import { ApiError } from '../api/client';
import userEvent from '@testing-library/user-event';
import { Routes, Route, useParams } from 'react-router';
import { renderWithProviders } from '../test/utils';
import { caseFixture } from '../test/fixtures';
import { EditCasePage } from './EditCasePage';
import * as casesApi from '../api/cases';
import * as roomsApi from '../api/rooms';
import type { RoomRead } from '../types';

vi.mock('../api/cases', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), getCase: vi.fn(), updateCase: vi.fn() };
});
vi.mock('../api/rooms', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), listRooms: vi.fn() };
});

const cases = vi.mocked(casesApi);
const rooms = vi.mocked(roomsApi);

const study: RoomRead = {
  id: 1, name: 'Study', case_count: 1, loose_hat_count: 0, is_default: true,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
};

function CaseLanding() {
  const { displayId } = useParams();
  return <p>{`Landed on ${displayId}`}</p>;
}

function renderEdit() {
  return renderWithProviders(
    <Routes>
      <Route path="/cases/:displayId/edit" element={<EditCasePage />} />
      <Route path="/cases/:displayId" element={<CaseLanding />} />
    </Routes>,
    { route: '/cases/A-001/edit' },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  cases.getCase.mockResolvedValue({ ...caseFixture({ display_id: 'A-001', room_id: 1, room_name: 'Study' }), hats: [] });
  rooms.listRooms.mockResolvedValue([study]);
});

describe('EditCasePage', () => {
  it('warns about the renumber, and lands on the NEW id after a type change', async () => {
    cases.updateCase.mockResolvedValue(caseFixture({ display_id: 'D-004', case_type: 'daily_wear' }));
    const user = userEvent.setup();
    renderEdit();

    const type = await screen.findByRole('combobox', { name: 'Case type' });
    await screen.findByRole('option', { name: 'Study' });
    expect(screen.queryByRole('note')).not.toBeInTheDocument();

    await user.selectOptions(type, 'daily_wear');
    expect(screen.getByRole('note')).toHaveTextContent(/renumbers this case — A-001 becomes the\s+next D-###/);
    // The server never issues a number twice (`case_service.get_next_sequence`),
    // so the stale label finds nothing rather than another case — and says so.
    expect(screen.getByRole('note')).toHaveTextContent(/never reused, so it can.t open a different case/);

    await user.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(cases.updateCase).toHaveBeenCalledWith('A-001', { case_type: 'daily_wear', room_id: 1, capacity: null });
    expect(await screen.findByText('Landed on D-004')).toBeInTheDocument();
    expect(await screen.findByText('Case saved as D-004')).toBeInTheDocument();
  });

  it('an ordinary save returns to the same case, with no warning', async () => {
    cases.updateCase.mockResolvedValue(caseFixture({ display_id: 'A-001', capacity: 4 }));
    const user = userEvent.setup();
    renderEdit();

    const capacity = await screen.findByRole('spinbutton', { name: 'Capacity (hats)' });
    await screen.findByRole('option', { name: 'Study' });
    await user.type(capacity, '4');
    expect(screen.queryByRole('note')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(cases.updateCase).toHaveBeenCalledWith('A-001', { case_type: 'archive', room_id: 1, capacity: 4 });
    expect(await screen.findByText('Landed on A-001')).toBeInTheDocument();
    expect(await screen.findByText('Case saved')).toBeInTheDocument();
  });

  it('says so when the room list fails, instead of an empty picker', async () => {
    rooms.listRooms.mockRejectedValue(new Error('database is locked'));
    renderEdit();

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load rooms — database is locked');
    expect(screen.getByRole('combobox', { name: 'Room' })).toBeInTheDocument();
  });

  it('shows an orphaned case in its own (missing) room, not the first room in the list', async () => {
    // With no option matching its value, the select displayed "Study" while
    // the form meant room 9 — the case detail page handled this, the Edit
    // form's copy of the select did not.
    cases.getCase.mockResolvedValue({ ...caseFixture({ display_id: 'A-001', room_id: 9, room_name: null }), hats: [] });
    renderEdit();

    await screen.findByRole('option', { name: 'Study' });
    const picker = screen.getByRole('combobox', { name: 'Room' });
    expect(picker).toHaveValue('9');
    expect(screen.getByRole('option', { name: 'No room' })).toBeInTheDocument();
  });

  it('keeps what was typed when the case refetches mid-edit', async () => {
    // The seed used to re-run on every refetch (this query refetches on
    // window focus), reverting a half-edited form to the server's values.
    const user = userEvent.setup();
    renderEdit();
    const capacity = await screen.findByRole('spinbutton', { name: 'Capacity (hats)' });
    await user.type(capacity, '5');

    cases.getCase.mockResolvedValue({ ...caseFixture({ display_id: 'A-001', room_id: 1, room_name: 'Study', capacity: 2 }), hats: [] });
    focusManager.setFocused(false);
    focusManager.setFocused(true);
    await waitFor(() => expect(cases.getCase.mock.calls.length).toBeGreaterThan(1));
    await new Promise(r => setTimeout(r, 20));

    expect(capacity).toHaveValue(5);
  });

  it('says a missing case is missing, with the way back to the list', async () => {
    cases.getCase.mockRejectedValue(new ApiError('Case not found', 404));
    renderEdit();

    expect(await screen.findByText('Case not found')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to cases' })).toHaveAttribute('href', '/cases');
  });

  it('keeps a failed save on the form and says why', async () => {
    cases.updateCase.mockRejectedValue(new Error('Room 9 not found'));
    const user = userEvent.setup();
    renderEdit();

    await screen.findByRole('option', { name: 'Study' });
    await user.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save — Room 9 not found');
    expect(screen.getByRole('heading', { name: 'Edit case A-001' })).toBeInTheDocument();
  });
});
