/**
 * The quick "new case" dialog on the hat forms.
 *
 * Its two selects were named only by `aria-label` beside a visible `<label>`
 * that pointed at nothing; they are paired by id now. The footer's Create
 * button submits the dialog's form through `form=`.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { caseFixture } from '../../test/fixtures';
import { NewCaseModal } from './NewCaseModal';
import * as casesApi from '../../api/cases';
import * as roomsApi from '../../api/rooms';
import type { RoomRead } from '../../types';

vi.mock('../../api/cases', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), createCase: vi.fn() };
});
vi.mock('../../api/rooms', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
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

beforeEach(() => {
  vi.clearAllMocks();
  rooms.listRooms.mockResolvedValue([aRoom(1, 'Main'), aRoom(2, 'Den', true)]);
  cases.createCase.mockResolvedValue(caseFixture({ id: 9, display_id: 'D-003', case_type: 'daily_wear' }));
});

describe('NewCaseModal', () => {
  it('creates in the chosen type and the default room, then hands back the new id', async () => {
    const onCreated = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<NewCaseModal show onClose={onClose} onCreated={onCreated} />);

    await screen.findByRole('dialog', { name: 'New case' });
    await screen.findByRole('option', { name: 'Den' });
    expect(screen.getByRole('combobox', { name: 'Room' })).toHaveValue('2');

    await user.selectOptions(screen.getByRole('combobox', { name: 'Case type' }), 'daily_wear');
    await user.click(screen.getByRole('button', { name: 'Create case' }));

    expect(cases.createCase).toHaveBeenCalledWith('daily_wear', 2);
    await vi.waitFor(() => expect(onCreated).toHaveBeenCalledWith(9));
    expect(onClose).toHaveBeenCalled();
    expect(await screen.findByText('Case D-003 created')).toBeInTheDocument();
  });

  it('is the New case page’s own fields — a failed room list is named as such', async () => {
    // The dialog kept a third copy of the type and room selects, and reported
    // a failed room list as a bare reason with no word of what had failed.
    rooms.listRooms.mockRejectedValue(new Error('database is locked'));
    renderWithProviders(<NewCaseModal show onClose={() => {}} onCreated={() => {}} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load rooms — database is locked');
    expect(screen.getByRole('combobox', { name: 'Case type' })).toHaveValue('archive');
  });

  it('renders nothing while hidden, and fetches nothing', () => {
    renderWithProviders(<NewCaseModal show={false} onClose={() => {}} onCreated={() => {}} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(rooms.listRooms).not.toHaveBeenCalled();
  });
});
