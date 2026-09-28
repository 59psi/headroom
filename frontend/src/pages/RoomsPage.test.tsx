/**
 * The Rooms tab edits in place.
 *
 * Renaming used to open a separate card at the TOP of the page — far from
 * the row on any list longer than a screen — and deleting used the browser's
 * own `confirm()`, a gray system sheet iOS standalone apps suppress after a
 * few appearances. Now a row renames itself (Enter saves, Escape cancels),
 * every change shows at once and is rolled back if the server refuses it, and
 * the delete warning is an in-app dialog that still names where the contents
 * go.
 *
 * The API is a small fake server so the refetch that follows every mutation
 * returns what the server would — a static mock would "revert" a rename the
 * moment the list was refetched, and the test would be asserting the mock.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../test/utils';
import { RoomsPage } from './RoomsPage';
import * as roomsApi from '../api/rooms';
import type { RoomRead } from '../types';

vi.mock('../api/rooms', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    listRooms: vi.fn(),
    createRoom: vi.fn(),
    updateRoom: vi.fn(),
    deleteRoom: vi.fn(),
    setDefaultRoom: vi.fn(),
  };
});

const api = vi.mocked(roomsApi);

function room(over: Partial<RoomRead>): RoomRead {
  return {
    id: 1, name: 'Main', case_count: 0, loose_hat_count: 0, is_default: false,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    ...over,
  };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

let server: RoomRead[];

beforeEach(() => {
  vi.clearAllMocks();
  server = [
    room({ id: 1, name: 'Main', is_default: true, case_count: 3 }),
    room({ id: 2, name: 'Study', case_count: 2, loose_hat_count: 1 }),
  ];
  api.listRooms.mockImplementation(async () => server.map(r => ({ ...r })));
  api.updateRoom.mockImplementation(async (id, name) => {
    server = server.map(r => (r.id === id ? { ...r, name } : r));
    return server.find(r => r.id === id)!;
  });
  api.createRoom.mockImplementation(async name => {
    const made = room({ id: 3, name });
    server = [...server, made];
    return made;
  });
  api.deleteRoom.mockImplementation(async id => {
    server = server.filter(r => r.id !== id);
  });
  api.setDefaultRoom.mockImplementation(async id => {
    server = server.map(r => ({ ...r, is_default: r.id === id }));
    return server.find(r => r.id === id)!;
  });
});

/**
 * Make every refetch after the first load hang. Each mutation invalidates
 * the list when it settles, and a refetch from the fake server would repair
 * the screen by itself — so a rollback (or an insert from the server's
 * answer) that never happened would still look right. Frozen, only the
 * mutation's own cache write can change what is shown.
 */
async function freezeRefetchesAfterLoad() {
  await screen.findByRole('list');
  api.listRooms.mockImplementation(() => new Promise(() => {}));
}

/** The link into a room. Its name runs straight on into the counts
 *  ("Study2 cases") in jsdom, which has no layout to space flex items. */
function roomLink(name: string) {
  return screen.getByRole('link', { name: new RegExp(`^${name}(Default)?\\d`) });
}

function queryRoomLink(name: string) {
  return screen.queryByRole('link', { name: new RegExp(`^${name}(Default)?\\d`) });
}

/** The row (`<li>`) for a room. */
function row(name: string) {
  return roomLink(name).closest('li')!;
}

describe('RoomsPage', () => {
  it('renames a row in place: Enter saves, and the new name shows before the server answers', async () => {
    const pending = deferred<RoomRead>();
    api.updateRoom.mockImplementationOnce(() => pending.promise);
    const user = userEvent.setup();
    renderWithProviders(<RoomsPage />, { route: '/rooms' });

    await user.click(await screen.findByRole('button', { name: 'Rename Study' }));
    const field = screen.getByRole('textbox', { name: 'New name for Study' });
    // Opens holding the current name, selected, so typing replaces it.
    expect(field).toHaveValue('Study');
    expect(field).toHaveFocus();
    await user.keyboard('Den{Enter}');

    expect(api.updateRoom).toHaveBeenCalledWith(2, 'Den');
    // Optimistic: the row already reads "Den" while the request is in flight.
    expect(roomLink('Den')).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'New name for Study' })).not.toBeInTheDocument();

    server = server.map(r => (r.id === 2 ? { ...r, name: 'Den' } : r));
    pending.resolve({ ...server[1] });
    expect(await screen.findByText('Renamed to “Den”')).toBeInTheDocument();
    // Focus goes back to the row's Rename button, not to <body>.
    expect(screen.getByRole('button', { name: 'Rename Den' })).toHaveFocus();
  });

  it('Escape cancels a rename without sending anything', async () => {
    const user = userEvent.setup();
    renderWithProviders(<RoomsPage />, { route: '/rooms' });

    await user.click(await screen.findByRole('button', { name: 'Rename Study' }));
    await user.keyboard('Something else{Escape}');

    expect(api.updateRoom).not.toHaveBeenCalled();
    expect(roomLink('Study')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rename Study' })).toHaveFocus();
  });

  it('saving the name unchanged just closes the field', async () => {
    const user = userEvent.setup();
    renderWithProviders(<RoomsPage />, { route: '/rooms' });

    await user.click(await screen.findByRole('button', { name: 'Rename Study' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(api.updateRoom).not.toHaveBeenCalled();
    expect(screen.queryByRole('textbox', { name: 'New name for Study' })).not.toBeInTheDocument();
  });

  it('a refused rename puts the old name back and says why, under that row', async () => {
    api.updateRoom.mockRejectedValueOnce(new Error('Name is too long'));
    const user = userEvent.setup();
    renderWithProviders(<RoomsPage />, { route: '/rooms' });
    await freezeRefetchesAfterLoad();

    await user.click(await screen.findByRole('button', { name: 'Rename Study' }));
    await user.keyboard('Den{Enter}');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Could not rename — Name is too long');
    // The field comes back holding what was typed, so a retry is one press
    // of Enter — the separate rename card this replaced stayed open on a
    // failure, and a failed request must not cost the typing too.
    const field = screen.getByRole('textbox', { name: 'New name for Study' });
    expect(field).toHaveValue('Den');
    expect(field.closest('li')).toContainElement(alert);

    // Closing it shows the rolled-back name: refetches are frozen, so only
    // the mutation's own rollback can have put "Study" back.
    await user.keyboard('{Escape}');
    expect(roomLink('Study')).toBeInTheDocument();
    expect(queryRoomLink('Den')).not.toBeInTheDocument();
    expect(row('Study')).toContainElement(screen.getByRole('alert'));
  });

  it('a refused rename retried from the reopened field sends the typed name', async () => {
    api.updateRoom.mockRejectedValueOnce(new Error('Server unreachable'));
    const user = userEvent.setup();
    renderWithProviders(<RoomsPage />, { route: '/rooms' });

    await user.click(await screen.findByRole('button', { name: 'Rename Study' }));
    await user.keyboard('Den{Enter}');
    await screen.findByRole('alert');

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(api.updateRoom).toHaveBeenLastCalledWith(2, 'Den');
    expect(await screen.findByText('Renamed to “Den”')).toBeInTheDocument();
    expect(roomLink('Den')).toBeInTheDocument();
  });

  it('a refused rename does not take focus from another field', async () => {
    const pending = deferred<RoomRead>();
    api.updateRoom.mockImplementationOnce(() => pending.promise);
    const user = userEvent.setup();
    renderWithProviders(<RoomsPage />, { route: '/rooms' });

    await user.click(await screen.findByRole('button', { name: 'Rename Study' }));
    await user.keyboard('Den{Enter}');
    // The person has moved on to adding a room while the rename is in flight.
    const add = screen.getByRole('textbox', { name: 'Add room' });
    await user.click(add);
    pending.reject(new Error('Server unreachable'));

    expect(await screen.findByRole('textbox', { name: 'New name for Study' })).toHaveValue('Den');
    expect(add).toHaveFocus();
  });

  it('asks in the app before deleting, naming where the contents go — and Cancel deletes nothing', async () => {
    const user = userEvent.setup();
    renderWithProviders(<RoomsPage />, { route: '/rooms' });

    await user.click(await screen.findByRole('button', { name: 'Delete Study' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText('Delete “Study”?')).toBeInTheDocument();
    // The original warning, including the loose hats and the real default.
    expect(within(dialog).getByText('Its 2 cases and 1 loose hat will move to Main.')).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(api.deleteRoom).not.toHaveBeenCalled();
    expect(roomLink('Study')).toBeInTheDocument();
  });

  it('deletes once confirmed, and the row goes at once', async () => {
    const pending = deferred<void>();
    api.deleteRoom.mockImplementationOnce(() => pending.promise);
    const user = userEvent.setup();
    renderWithProviders(<RoomsPage />, { route: '/rooms' });

    await user.click(await screen.findByRole('button', { name: 'Delete Study' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete room' }));

    expect(api.deleteRoom).toHaveBeenCalledWith(2);
    await waitFor(() => expect(queryRoomLink('Study')).not.toBeInTheDocument());

    server = server.filter(r => r.id !== 2);
    pending.resolve();
    expect(await screen.findByText('Deleted “Study”')).toBeInTheDocument();
  });

  it('a refused delete brings the row back, with the reason under it', async () => {
    const pending = deferred<void>();
    api.deleteRoom.mockImplementationOnce(() => pending.promise);
    const user = userEvent.setup();
    renderWithProviders(<RoomsPage />, { route: '/rooms' });
    await freezeRefetchesAfterLoad();

    await user.click(await screen.findByRole('button', { name: 'Delete Study' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete room' }));
    await waitFor(() => expect(queryRoomLink('Study')).not.toBeInTheDocument());

    pending.reject(new Error('database is locked'));

    // Refetches are frozen: only the mutation's rollback can restore the row.
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not delete — database is locked');
    expect(row('Study')).toContainElement(screen.getByRole('alert'));
    expect(screen.queryByText('Deleted “Study”')).not.toBeInTheDocument();
  });

  it('a failed load says so, with no empty list and no add field', async () => {
    api.listRooms.mockRejectedValue(new Error('database is locked'));
    renderWithProviders(<RoomsPage />, { route: '/rooms' });

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load rooms — database is locked');
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Add room' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', '/');
  });

  it('never offers to delete the default room', async () => {
    renderWithProviders(<RoomsPage />, { route: '/rooms' });
    expect(await screen.findByRole('button', { name: 'Delete Main' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Make default: Main' })).toBeDisabled();
  });

  it('adds a room without leaving the page, straight from the server’s answer', async () => {
    const user = userEvent.setup();
    renderWithProviders(<RoomsPage />, { route: '/rooms' });
    await freezeRefetchesAfterLoad();

    await user.type(await screen.findByRole('textbox', { name: 'Add room' }), '  Garage  {Enter}');

    expect(api.createRoom).toHaveBeenCalledWith('Garage');
    expect(await screen.findByRole('link', { name: /^Garage\d/ })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Add room' })).toHaveValue('');
    expect(await screen.findByText('Added “Garage”')).toBeInTheDocument();
  });

  it('moves the default flag at once, and back if the server refuses', async () => {
    const pending = deferred<RoomRead>();
    api.setDefaultRoom.mockImplementationOnce(() => pending.promise);
    const user = userEvent.setup();
    renderWithProviders(<RoomsPage />, { route: '/rooms' });
    await freezeRefetchesAfterLoad();

    await user.click(await screen.findByRole('button', { name: 'Make default: Study' }));

    await waitFor(() => expect(within(row('Study')).getByText('Default')).toBeInTheDocument());
    expect(within(row('Main')).queryByText('Default')).not.toBeInTheDocument();

    pending.reject(new Error('Room not found'));

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not make this the default — Room not found');
    expect(within(row('Main')).getByText('Default')).toBeInTheDocument();
    expect(within(row('Study')).queryByText('Default')).not.toBeInTheDocument();
  });
});
