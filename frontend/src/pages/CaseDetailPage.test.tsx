/**
 * A case page moves the case in place and asks in-app before deleting it.
 *
 * Moving a case to another room took Edit → change the room → Save → back;
 * the room picker now sits on the case itself and applies on change, showing
 * the new room at once and putting the old one back if the server refuses.
 *
 * Deleting used the browser's `confirm()` and warned that the hats "will
 * become unassigned" — untrue since 2.57.1, when `delete_case` started
 * keeping them in the case's room as loose hats.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router';
import { renderWithProviders } from '../test/utils';
import { caseFixture } from '../test/fixtures';
import { CaseDetailPage } from './CaseDetailPage';
import * as casesApi from '../api/cases';
import * as roomsApi from '../api/rooms';
import * as settingsApi from '../api/settings';
import type { CaseDetail, CaseRead, RoomRead } from '../types';

vi.mock('../api/cases', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), getCase: vi.fn(), deleteCase: vi.fn(), updateCase: vi.fn() };
});
vi.mock('../api/rooms', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), listRooms: vi.fn() };
});
vi.mock('../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), getTagBase: vi.fn() };
});

const cases = vi.mocked(casesApi);
const rooms = vi.mocked(roomsApi);
const settings = vi.mocked(settingsApi);

function aRoom(id: number, name: string): RoomRead {
  return {
    id, name, case_count: 1, loose_hat_count: 0, is_default: id === 1,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

let server: CaseDetail;

beforeEach(() => {
  vi.clearAllMocks();
  server = {
    ...caseFixture({
      display_id: 'A-001', room_id: 1, room_name: 'Study',
      hat_count: 2, regular_count: 2, free_regular: 1,
    }),
    hats: [
      { id: 11, display_id: 'A-001-01', style: 'a_game', is_beanie: false, photo_path: null, thumb_path: null },
      { id: 12, display_id: 'A-001-02', style: 'odis', is_beanie: false, photo_path: null, thumb_path: null },
    ],
  };
  cases.getCase.mockImplementation(async () => ({ ...server }));
  cases.deleteCase.mockResolvedValue(undefined);
  cases.updateCase.mockImplementation(async (_id, body) => {
    const room = [aRoom(1, 'Study'), aRoom(2, 'Den')].find(r => r.id === body.room_id)!;
    server = { ...server, room_id: room.id, room_name: room.name };
    return server as CaseRead;
  });
  rooms.listRooms.mockResolvedValue([aRoom(1, 'Study'), aRoom(2, 'Den')]);
  settings.getTagBase.mockResolvedValue({ base_url: 'http://headroom.local' } as never);
});

function renderCase() {
  return renderWithProviders(
    <Routes>
      <Route path="/cases/:displayId" element={<CaseDetailPage />} />
      <Route path="/cases" element={<p>All cases</p>} />
    </Routes>,
    { route: '/cases/A-001' },
  );
}

describe('CaseDetailPage — delete', () => {
  it('asks in the app first, with the TRUE consequence — and Cancel deletes nothing', async () => {
    const user = userEvent.setup();
    renderCase();

    await user.click(await screen.findByRole('button', { name: 'Delete case' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText('Delete case A-001?')).toBeInTheDocument();
    expect(within(dialog).getByText('Its 2 hats stay in Study, out of a case. This can’t be undone.')).toBeInTheDocument();
    expect(within(dialog).queryByText(/unassigned/)).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(cases.deleteCase).not.toHaveBeenCalled();
  });

  it('deletes once confirmed, then returns to the list with a toast', async () => {
    const user = userEvent.setup();
    renderCase();

    await user.click(await screen.findByRole('button', { name: 'Delete case' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete case' }));

    expect(cases.deleteCase).toHaveBeenCalledWith('A-001');
    expect(await screen.findByText('All cases')).toBeInTheDocument();
    expect(await screen.findByText('Case A-001 deleted')).toBeInTheDocument();
  });

  it('keeps a failed delete on the page and says why', async () => {
    cases.deleteCase.mockRejectedValueOnce(new Error('database is locked'));
    const user = userEvent.setup();
    renderCase();

    await user.click(await screen.findByRole('button', { name: 'Delete case' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete case' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not delete — database is locked');
    expect(screen.queryByText('All cases')).not.toBeInTheDocument();
  });
});

describe('CaseDetailPage — move to another room', () => {
  it('applies on change, showing the new room before the server answers', async () => {
    const pending = deferred<CaseRead>();
    cases.updateCase.mockImplementationOnce(() => pending.promise);
    const user = userEvent.setup();
    renderCase();

    const picker = await screen.findByRole('combobox', { name: 'Room' });
    // Wait for the full room list, not just the case's own room.
    await screen.findByRole('option', { name: 'Den' });
    await user.selectOptions(picker, 'Den');

    expect(cases.updateCase).toHaveBeenCalledWith('A-001', { room_id: 2 });
    expect(picker).toHaveValue('2');
    // The head's room link follows at once, and the picker says it is saving.
    expect(screen.getByRole('link', { name: 'Den' })).toHaveAttribute('href', '/rooms/2');
    expect(screen.getByText('Saving…')).toBeInTheDocument();
    // One move at a time.
    expect(picker).toBeDisabled();

    server = { ...server, room_id: 2, room_name: 'Den' };
    pending.resolve(server as CaseRead);
    expect(await screen.findByText('Saved')).toBeInTheDocument();
    expect(picker).toBeEnabled();
  });

  it('says so when the room list fails, rather than offering one room as if it were all', async () => {
    rooms.listRooms.mockRejectedValue(new Error('database is locked'));
    renderCase();

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load rooms — database is locked');
    // The picker still names the case's own room.
    expect(screen.getByRole('combobox', { name: 'Room' })).toHaveValue('1');
  });

  it('can move a case whose room is missing from the list — even to the first room', async () => {
    // A case orphaned by an older version: its room id names no room.
    server = { ...server, room_id: 99, room_name: 'Unknown' };
    const user = userEvent.setup();
    renderCase();

    const picker = await screen.findByRole('combobox', { name: 'Room' });
    await screen.findByRole('option', { name: 'Den' });
    // Showing its real (missing) room, not silently the first option — which
    // the browser would treat as already chosen, so picking it did nothing.
    expect(picker).toHaveValue('99');
    await user.selectOptions(picker, 'Study');

    expect(cases.updateCase).toHaveBeenCalledWith('A-001', { room_id: 1 });
  });

  it('puts the old room back, with the reason, when the server refuses', async () => {
    cases.updateCase.mockRejectedValueOnce(new Error('Room 2 not found'));
    const user = userEvent.setup();
    renderCase();

    const picker = await screen.findByRole('combobox', { name: 'Room' });
    await screen.findByRole('option', { name: 'Den' });
    // Hang the refetch that follows the failure, so only the mutation's own
    // rollback can put Study back — a refetch would repair the screen and
    // hide a rollback that never ran.
    cases.getCase.mockImplementation(() => new Promise(() => {}));
    await user.selectOptions(picker, 'Den');

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not move this case — Room 2 not found');
    expect(picker).toHaveValue('1');
    expect(screen.getByRole('link', { name: 'Study' })).toHaveAttribute('href', '/rooms/1');
    expect(screen.getByText('Not saved')).toBeInTheDocument();
  });
});
