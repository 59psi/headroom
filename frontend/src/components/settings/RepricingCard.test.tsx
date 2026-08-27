import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { RepricingCard } from './RepricingCard';
import * as api from '../../api/settings';
import type { RepricingStatus } from '../../types';

vi.mock('../../api/settings', () => ({
  getRepricing: vi.fn(),
  runRepricing: vi.fn(),
}));

const mocked = vi.mocked(api);

/** The real payload shape — every field pydantic serializes, defaults included. */
function status(over: Partial<RepricingStatus> = {}) {
  return {
    enabled: true, interval_hours: 24, last_run_at: null, last_success_at: null,
    last_error: null, consecutive_failures: 0, last_repriced: 0, last_considered: 0,
    ...over,
  } as RepricingStatus;
}

beforeEach(() => { vi.clearAllMocks(); });

describe('RepricingCard', () => {
  it('distinguishes "no sweep yet" from "a sweep that changed nothing"', async () => {
    // These look identical if you only report a timestamp, and only one of them
    // is a problem — a flat market is a working sweep.
    mocked.getRepricing.mockResolvedValue(status());
    const { unmount } = renderWithProviders(<RepricingCard />);
    expect(await screen.findByText('No sweep yet')).toBeInTheDocument();
    unmount();

    mocked.getRepricing.mockResolvedValue(status({
      last_success_at: '2026-08-27T04:00:00Z', last_repriced: 0, last_considered: 234,
    }));
    renderWithProviders(<RepricingCard />);
    expect(await screen.findByText('0 of 234 changed')).toBeInTheDocument();
  });

  it('offers a manual sweep even when the schedule is off', async () => {
    // Turning the background task off should not remove the ability to
    // refresh prices on purpose.
    const user = userEvent.setup();
    mocked.getRepricing.mockResolvedValue(status({ enabled: false }));
    mocked.runRepricing.mockResolvedValue({ repriced: 12, considered: 50, remaining: 234 });

    renderWithProviders(<RepricingCard />);
    expect(await screen.findByText(/Scheduled sweeps off/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Re-price now' }));

    expect(mocked.runRepricing).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText(/12 of 50 hats changed price/i),
    ).toBeInTheDocument();
    // A bounded run must say there is more, or "50 of 234" reads as a failure.
    expect(await screen.findByText(/press again to continue/i)).toBeInTheDocument();
  });

  it('surfaces a failing sweep rather than looking idle', async () => {
    mocked.getRepricing.mockResolvedValue(status({
      last_run_at: '2026-08-27T04:00:00Z',
      last_error: 'MelinRecapError: 429 Too Many Requests',
      consecutive_failures: 3,
    }));

    renderWithProviders(<RepricingCard />);

    expect(await screen.findByText(/429 Too Many Requests/)).toBeInTheDocument();
  });

  it('says prices you entered yourself are safe', async () => {
    // The single most important property of an automated re-pricer, and the
    // one a user has no way to verify from outside.
    mocked.getRepricing.mockResolvedValue(status());
    renderWithProviders(<RepricingCard />);
    expect(
      await screen.findByText(/Prices you entered yourself are never touched/i),
    ).toBeInTheDocument();
  });
});
