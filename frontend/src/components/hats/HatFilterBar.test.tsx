import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { useHatFilters, HatFilterBar, FilterToggleButton } from './HatFilters';

vi.mock('../../api/hats', () => ({
  getStyles: vi.fn(async () => [
    { value: 'a_game', label: 'A-Game' },
    { value: 'odysea', label: 'Odysea' },
  ]),
  getSizes: vi.fn(async () => [{ value: 'classic', label: 'Classic' }]),
  getConditions: vi.fn(async () => [{ value: 'new', label: 'New' }]),
  getConstructions: vi.fn(async () => ['HYDRO', 'HYDROLite', 'Thermal']),
}));

vi.mock('../../api/rooms', () => ({
  getRoomOptions: vi.fn(async () => [{ value: '3', label: 'Closet' }]),
}));

/** Stands in for a page: owns the hook, renders the bar, exposes state as text. */
function Harness({ withExtra = false }: { withExtra?: boolean }) {
  const state = useHatFilters();
  return (
    <>
      <div data-testid="active">{state.activeCount}</div>
      <div data-testid="style">{state.filters.style}</div>
      <div data-testid="room">{state.filters.room}</div>
      <HatFilterBar state={state} colors={['blue', 'red']}>
        {withExtra && (
          <div className="col-6 col-md-3">
            <label className="form-label">Brand</label>
            <select aria-label="Brand"><option value="">All</option></select>
          </div>
        )}
      </HatFilterBar>
    </>
  );
}

beforeEach(() => { vi.clearAllMocks(); });

describe('HatFilterBar', () => {
  it('renders the six shared selects, populated from the meta queries', async () => {
    renderWithProviders(<Harness />);
    for (const label of ['Style', 'Size', 'Condition', 'Type', 'Color', 'Room']) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    // Options arrive asynchronously; the Type select is hard-coded.
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'A-Game' })).toBeInTheDocument();
    });
    expect(screen.getByRole('option', { name: 'Closet' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Beanies' })).toBeInTheDocument();
  });

  it('offers the colors it is handed, not a hard-coded palette', () => {
    renderWithProviders(<Harness />);
    const color = screen.getByLabelText('Color') as HTMLSelectElement;
    expect([...color.options].map(o => o.value)).toEqual(['', 'blue', 'red']);
  });

  it('updates filter state and the active count as selections are made', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);
    await waitFor(() => screen.getByRole('option', { name: 'Odysea' }));

    expect(screen.getByTestId('active')).toHaveTextContent('0');
    await user.selectOptions(screen.getByLabelText('Style'), 'odysea');
    expect(screen.getByTestId('style')).toHaveTextContent('odysea');
    expect(screen.getByTestId('active')).toHaveTextContent('1');

    await user.selectOptions(screen.getByLabelText('Room'), '3');
    expect(screen.getByTestId('active')).toHaveTextContent('2');
  });

  it('hides Clear until something is set, then resets every shared filter', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);
    await waitFor(() => screen.getByRole('option', { name: 'Odysea' }));

    expect(screen.queryByRole('button', { name: /clear filters/i })).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Style'), 'odysea');
    await user.selectOptions(screen.getByLabelText('Room'), '3');
    await user.click(screen.getByRole('button', { name: /clear filters/i }));

    expect(screen.getByTestId('style')).toHaveTextContent('');
    expect(screen.getByTestId('room')).toHaveTextContent('');
    expect(screen.getByTestId('active')).toHaveTextContent('0');
  });

  it('renders page-specific extras and clears them alongside the shared ones', async () => {
    // The Hats page passes Brand as a child plus onClearExtras; if Clear only
    // reset the shared six, its brand filter would silently stay applied.
    const user = userEvent.setup();
    const onClearExtras = vi.fn();

    function WithExtras() {
      const state = useHatFilters();
      return (
        <HatFilterBar
          state={state}
          colors={[]}
          activeCount={state.activeCount + 1}
          onClearExtras={onClearExtras}
        >
          <select aria-label="Brand"><option value="">All</option></select>
        </HatFilterBar>
      );
    }

    renderWithProviders(<WithExtras />);
    expect(screen.getByLabelText('Brand')).toBeInTheDocument();
    // activeCount is overridden to 1, so Clear shows even with nothing shared set.
    await user.click(screen.getByRole('button', { name: /clear filters/i }));
    expect(onClearExtras).toHaveBeenCalledOnce();
  });
});

describe('FilterToggleButton', () => {
  it('shows a count badge only when filters are active, and toggles', async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    const { rerender } = renderWithProviders(
      <FilterToggleButton activeCount={0} isOpen={false} onToggle={onToggle} />,
    );
    expect(screen.getByRole('button')).toHaveTextContent(/^Filters$/);

    rerender(<FilterToggleButton activeCount={3} isOpen={false} onToggle={onToggle} />);
    expect(screen.getByRole('button')).toHaveTextContent('3');

    await user.click(screen.getByRole('button'));
    expect(onToggle).toHaveBeenCalledWith(true);
  });
});
