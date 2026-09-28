import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { caseFixture } from '../../test/fixtures';
import { CasePicker } from './CasePicker';

const cases = [
  caseFixture({ id: 1, display_id: 'A-001', case_type: 'archive', room_name: 'Closet' }),
  caseFixture({ id: 2, display_id: 'D-001', case_type: 'daily_wear', room_name: 'Hallway' }),
  caseFixture({ id: 3, display_id: 'A-002', case_type: 'archive', room_name: null }),
];

function open() {
  renderWithProviders(
    <CasePicker label="Case" value="" onChange={vi.fn()} cases={cases} isBeanie={false} onCreateCase={vi.fn()} />,
  );
  return screen.getByRole('combobox', { name: 'Case' });
}

describe('CasePicker', () => {
  it('finds a daily case by the words its rows print — "Daily wear", as on every other screen', async () => {
    const user = userEvent.setup();
    await user.type(open(), 'daily wear');
    expect(screen.getByRole('option', { name: /D-001/ })).toHaveTextContent('Daily wear');
    expect(screen.queryByRole('option', { name: /A-001/ })).not.toBeInTheDocument();
  });

  it('files an orphaned case under "No room" and finds it by that name', async () => {
    const user = userEvent.setup();
    await user.type(open(), 'no room');
    expect(screen.getByRole('option', { name: /A-002/ })).toHaveTextContent('No room');
    expect(screen.queryByRole('option', { name: /D-001/ })).not.toBeInTheDocument();
  });
});
