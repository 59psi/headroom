import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { RepricingCard } from './RepricingCard';
import * as api from '../../api/settings';
import type { RepricingStatus, SweepProgress } from '../../types';

vi.mock('../../api/settings', () => ({
  getRepricing: vi.fn(),
  runRepricing: vi.fn(),
}));

const mocked = vi.mocked(api);

/** Idle progress — what the server sends when nothing is sweeping. */
export function idleProgress(over: Partial<SweepProgress> = {}): SweepProgress {
  return {
    running: false, done: 0, total: 0, label: null,
    started_at: null, finished_at: null, error: null, pct: 0,
    ...over,
  };
}

/** The real payload shape — every field pydantic serializes, defaults included.
 *
 *  Deliberately NOT cast with `as`: the cast this replaced meant adding a
 *  required field to `RepricingStatus` left the fixture silently incomplete
 *  and typecheck green, which is the one thing the fixture exists to prevent. */
function status(over: Partial<RepricingStatus> = {}): RepricingStatus {
  return {
    enabled: true, interval_hours: 24, last_run_at: null, last_success_at: null,
    last_error: null, consecutive_failures: 0, last_repriced: 0, last_considered: 0,
    progress: idleProgress(),
    ...over,
  };
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

describe('RepricingCard — live progress', () => {
  it('shows a bar and what it is on while a sweep runs', async () => {
    // The scheduled sweep starts at boot and runs for minutes. Without this the
    // card could only describe the last run that FINISHED, so a sweep in
    // progress was indistinguishable from nothing happening at all.
    mocked.getRepricing.mockResolvedValue(status({
      progress: idleProgress({
        running: true, done: 37, total: 235, pct: 16,
        label: 'Odysea Rope Hydro', started_at: new Date().toISOString(),
      }),
    }));

    renderWithProviders(<RepricingCard />);

    const bar = await screen.findByRole('progressbar', { name: 'Sweep progress' });
    expect(bar).toHaveAttribute('aria-valuenow', '37');
    expect(bar).toHaveAttribute('aria-valuemax', '235');
    expect(screen.getByText('37 / 235')).toBeInTheDocument();
    // The useful half: a count says it is alive, the label says it is not
    // wedged on one hat.
    expect(screen.getByText('Odysea Rope Hydro')).toBeInTheDocument();
  });

  it('shows no bar when nothing is sweeping', async () => {
    // A permanently-present empty bar reads as a stalled job.
    mocked.getRepricing.mockResolvedValue(status());
    renderWithProviders(<RepricingCard />);
    await screen.findByRole('button', { name: /Re-price now/ });
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('still reports a failure after the sweep has stopped', async () => {
    // Nobody is watching at the moment it fails, so the error has to outlive
    // `running` going false or it can never be read at all.
    mocked.getRepricing.mockResolvedValue(status({
      progress: idleProgress({
        running: false, error: 'Melin Recap query 429',
        finished_at: new Date().toISOString(),
      }),
    }));

    renderWithProviders(<RepricingCard />);
    expect(await screen.findByText(/Melin Recap query 429/)).toBeInTheDocument();
  });
});
