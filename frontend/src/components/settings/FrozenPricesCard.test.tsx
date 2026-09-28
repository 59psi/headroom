import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { FrozenPricesCard } from './FrozenPricesCard';
import * as api from '../../api/settings';
import type { FrozenPriceRow, PriceReleaseResult } from '../../types';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    auditFrozenPrices: vi.fn(),
    releaseFrozenPrices: vi.fn(),
  };
});

const mocked = vi.mocked(api);

function row(over: Partial<FrozenPriceRow> = {}): FrozenPriceRow {
  return {
    hat_id: 1, display_id: null, model_name: 'Trenches Hydro', resale_price: 85,
    estimated_new_price: null, was_market_priced: false,
    ...over,
  };
}

const ROWS = [
  row({ hat_id: 11, model_name: 'Odysea Rope Hydro', was_market_priced: true }),
  row({ hat_id: 12, model_name: 'A-Game Icon' }),
];

beforeEach(() => { vi.clearAllMocks(); });

describe('FrozenPricesCard', () => {
  it('counts the frozen hats in the header, or says there is nothing to do', async () => {
    mocked.auditFrozenPrices.mockResolvedValue(ROWS);
    const { unmount } = renderWithProviders(<FrozenPricesCard />);
    expect(await screen.findByText('2 hats')).toBeInTheDocument();
    unmount();

    mocked.auditFrozenPrices.mockResolvedValue([]);
    renderWithProviders(<FrozenPricesCard />);
    expect(await screen.findByText('Nothing to do')).toBeInTheDocument();
    expect(screen.getByText(/No hat is holding a price/)).toBeInTheDocument();
  });

  it('releases only the ticked hats', async () => {
    const user = userEvent.setup();
    mocked.auditFrozenPrices.mockResolvedValue(ROWS);
    mocked.releaseFrozenPrices.mockResolvedValue({ dry_run: false, released: 1, hats: [] });
    renderWithProviders(<FrozenPricesCard />);

    const release = await screen.findByRole('button', { name: 'Release' });
    expect(release).toBeDisabled();

    await user.click(screen.getByLabelText('Release hat 12'));
    await user.click(screen.getByRole('button', { name: 'Release 1' }));

    expect(mocked.releaseFrozenPrices).toHaveBeenCalledWith([12], false);
    expect(await screen.findByText('Released 1 price')).toBeInTheDocument();
  });

  it('drops released rows at once, before the server answers', async () => {
    const user = userEvent.setup();
    mocked.auditFrozenPrices.mockResolvedValue(ROWS);
    mocked.releaseFrozenPrices.mockReturnValue(new Promise<PriceReleaseResult>(() => {}));
    renderWithProviders(<FrozenPricesCard />);

    await user.click(await screen.findByLabelText('Release hat 11'));
    await user.click(screen.getByRole('button', { name: 'Release 1' }));

    await waitFor(() => expect(screen.queryByLabelText('Release hat 11')).toBeNull());
    expect(screen.getByLabelText('Release hat 12')).toBeInTheDocument();
    expect(screen.getByText('1 hat')).toBeInTheDocument();
  });

  it('puts rows and the selection back when a release fails', async () => {
    // A retry should be one tap, not re-ticking the list.
    const user = userEvent.setup();
    mocked.auditFrozenPrices.mockResolvedValue(ROWS);
    mocked.releaseFrozenPrices.mockRejectedValue(new Error('database is locked'));
    renderWithProviders(<FrozenPricesCard />);

    await user.click(await screen.findByRole('button', { name: 'Select all' }));
    await user.click(screen.getByRole('button', { name: 'Release 2' }));

    expect(await screen.findByText(/database is locked/)).toBeInTheDocument();
    expect(screen.getByLabelText('Release hat 11')).toBeChecked();
    expect(screen.getByLabelText('Release hat 12')).toBeChecked();
    expect(screen.getByRole('button', { name: 'Release 2' })).toBeEnabled();
  });

  it('select all turns into select none', async () => {
    const user = userEvent.setup();
    mocked.auditFrozenPrices.mockResolvedValue(ROWS);
    renderWithProviders(<FrozenPricesCard />);

    await user.click(await screen.findByRole('button', { name: 'Select all' }));
    expect(screen.getByLabelText('Release hat 11')).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Select none' }));
    expect(screen.getByLabelText('Release hat 11')).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Release' })).toBeDisabled();
  });

  it('explains "was market-priced" where it appears', async () => {
    mocked.auditFrozenPrices.mockResolvedValue(ROWS);
    renderWithProviders(<FrozenPricesCard />);
    const tag = await screen.findByText(/was market-priced/, { selector: '.text-warning' });
    expect(tag).toHaveAttribute('title', expect.stringMatching(/fingerprint of the bug/));
  });
});
