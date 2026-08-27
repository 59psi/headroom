import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { AnalysisQueueCard } from './AnalysisQueueCard';
import * as settingsApi from '../../api/settings';
import type { AnalysisQueueStatus } from '../../api/settings';

vi.mock('../../api/settings', () => ({
  getAnalysisQueue: vi.fn(),
  getAnalysisFailures: vi.fn(async () => []),
  reanalyzeAll: vi.fn(),
  retryFailedAnalysis: vi.fn(),
}));

const IDLE: AnalysisQueueStatus = {
  worker_alive: true,
  queued: 0,
  pending_count: 0,
  pending: [],
  current_job: null,
  recent_jobs: [],
};

function queue(over: Partial<AnalysisQueueStatus>): AnalysisQueueStatus {
  return { ...IDLE, ...over };
}

describe('AnalysisQueueCard', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows progress for a run in flight', async () => {
    vi.mocked(settingsApi.getAnalysisQueue).mockResolvedValue(
      queue({
        pending_count: 173,
        current_job: {
          id: 4, total: 213, done: 40, failed: 3, status: 'running',
          started_at: new Date(Date.now() - 120_000).toISOString(),
          finished_at: null,
        },
      }),
    );

    renderWithProviders(<AnalysisQueueCard />);

    expect(await screen.findByText('40 / 213')).toBeInTheDocument();
    // The bar is the whole point — a count alone doesn't read as progress.
    const bar = screen.getByRole('progressbar', { name: 'Re-analysis progress' });
    expect(bar).toHaveAttribute('aria-valuenow', '40');
    expect(bar).toHaveAttribute('aria-valuemax', '213');
    expect(screen.getByText(/3 failed/)).toBeInTheDocument();
  });

  it('surfaces a backlog that nothing is draining', async () => {
    // The failure worth seeing: hats waiting with a dead worker means nothing
    // happens until a restart, and the bare count alone would look normal.
    vi.mocked(settingsApi.getAnalysisQueue).mockResolvedValue(
      queue({ worker_alive: false, pending_count: 12 }),
    );

    renderWithProviders(<AnalysisQueueCard />);

    expect(await screen.findByText(/no worker is/i)).toBeInTheDocument();
  });

  it('lists recent runs once nothing is in flight', async () => {
    vi.mocked(settingsApi.getAnalysisQueue).mockResolvedValue(
      queue({
        recent_jobs: [{
          id: 3, total: 213, done: 213, failed: 1, status: 'done',
          started_at: new Date(Date.now() - 90_000_000).toISOString(),
          finished_at: new Date(Date.now() - 86_400_000).toISOString(),
        }],
      }),
    );

    renderWithProviders(<AnalysisQueueCard />);

    expect(await screen.findByText('Recent runs')).toBeInTheDocument();
    expect(screen.getByText(/213\/213/)).toBeInTheDocument();
    expect(screen.getByText(/1 failed/)).toBeInTheDocument();
  });
});

describe('AnalysisQueueCard — why analysis is failing', () => {
  it('names the account, not the key, for a billing refusal', async () => {
    vi.mocked(settingsApi.getAnalysisQueue).mockResolvedValue(IDLE);
    vi.mocked(settingsApi.getAnalysisFailures).mockResolvedValue([
      {
        reason:
          'Claude analysis failed: Anthropic API error: Error code: 400 - ' +
          'Your credit balance is too low to access the Anthropic API.',
        hat_count: 235,
        retryable_count: 235,
        sample_hat_ids: [1, 2, 3],
        last_seen: '2026-08-23T22:26:44Z',
        is_billing: true,
      },
    ]);

    renderWithProviders(<AnalysisQueueCard />);

    // The count is the point: 235 hats failing for one reason is ONE problem.
    // Anchored, because the group's Retry button now also carries the count and
    // a bare /235 hats/ matches both.
    expect(await screen.findByText(/^235 hats ·/)).toBeInTheDocument();
    expect(screen.getByText(/your Anthropic ACCOUNT, not your key/)).toBeInTheDocument();
    // And the real error text, which used to be visible nowhere.
    expect(screen.getByText(/credit balance is too low/)).toBeInTheDocument();
  });
});

describe('AnalysisQueueCard — retrying only what failed', () => {
  const OVERLOAD = {
    reason:
      "Claude analysis failed: Anthropic API error: Error code: 529 - " +
      "{'type': 'error', 'error': {'type': 'overloaded_error'}}",
    hat_count: 21,
    retryable_count: 21,
    sample_hat_ids: [224, 223, 222],
    last_seen: '2026-08-25T10:00:00Z',
    is_billing: false,
  };
  const UNPARSED = {
    reason:
      'Claude analysis failed: Could not parse Claude response: string ' +
      "indices must be integers, not 'str'",
    hat_count: 1,
    retryable_count: 1,
    sample_hat_ids: [63],
    last_seen: '2026-08-25T10:01:00Z',
    is_billing: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(settingsApi.getAnalysisQueue).mockResolvedValue(IDLE);
    vi.mocked(settingsApi.retryFailedAnalysis).mockResolvedValue({
      queued: 21, worker_alive: true, job: null,
    });
  });

  it('retries one group without touching the other', async () => {
    // The two groups are not interchangeable: an overload wants retrying, a
    // response the parser choked on will choke again. One button for the whole
    // card would force them to be treated the same.
    const user = userEvent.setup();
    vi.mocked(settingsApi.getAnalysisFailures).mockResolvedValue([OVERLOAD, UNPARSED]);

    renderWithProviders(<AnalysisQueueCard />);

    await user.click(await screen.findByRole('button', { name: 'Retry 21 hats' }));

    expect(settingsApi.retryFailedAnalysis).toHaveBeenCalledWith(OVERLOAD.reason);
    expect(settingsApi.reanalyzeAll).not.toHaveBeenCalled();
  });

  it('offers one press for everything only when there is more than one group', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getAnalysisFailures).mockResolvedValue([OVERLOAD, UNPARSED]);

    renderWithProviders(<AnalysisQueueCard />);

    // 22, not 2 — the total is over hats, not over groups.
    await user.click(await screen.findByRole('button', { name: 'Retry all 22 failed hats' }));
    // `undefined` is what means "every failure" to the API client; a reason
    // here would silently narrow the run to one group.
    expect(settingsApi.retryFailedAnalysis).toHaveBeenCalledWith(undefined);
  });

  it('has no retry-all button for a single group, whose own button covers it', async () => {
    vi.mocked(settingsApi.getAnalysisFailures).mockResolvedValue([OVERLOAD]);

    renderWithProviders(<AnalysisQueueCard />);

    expect(await screen.findByRole('button', { name: 'Retry 21 hats' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Retry all/ })).not.toBeInTheDocument();
  });

  it('promises only what a retry can actually do', async () => {
    // A hat whose photo is gone is a real failure, worth showing, and one a
    // retry cannot fix. Labeling the button with `hat_count` would have it
    // promise work it cannot deliver.
    vi.mocked(settingsApi.getAnalysisFailures).mockResolvedValue([
      { ...OVERLOAD, hat_count: 21, retryable_count: 18 },
    ]);

    renderWithProviders(<AnalysisQueueCard />);

    expect(await screen.findByRole('button', { name: 'Retry 18 hats' })).toBeInTheDocument();
    expect(screen.getByText(/3 of these have no photo left/)).toBeInTheDocument();
  });

  it('explains a group that cannot be retried at all instead of a dead button', async () => {
    vi.mocked(settingsApi.getAnalysisFailures).mockResolvedValue([
      {
        reason: 'Photo missing before analysis could run.',
        hat_count: 2, retryable_count: 0, sample_hat_ids: [7, 8],
        last_seen: '2026-08-25T10:00:00Z', is_billing: false,
      },
    ]);

    renderWithProviders(<AnalysisQueueCard />);

    expect(await screen.findByText(/no photo left to analyze/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Retry/ })).not.toBeInTheDocument();
  });

  it('still confirms the retry after the failure it fixed disappears', async () => {
    // A successful retry clears the failures it queued, so the list empties and
    // unmounts on the next refetch. A banner nested inside that list would go
    // with it in the same render — the press would look like it did nothing,
    // which is exactly what it looks like when it genuinely does nothing.
    const user = userEvent.setup();
    vi.mocked(settingsApi.getAnalysisFailures)
      .mockResolvedValueOnce([OVERLOAD])
      .mockResolvedValue([]);

    renderWithProviders(<AnalysisQueueCard />);

    await user.click(await screen.findByRole('button', { name: 'Retry 21 hats' }));

    expect(await screen.findByText(/Queued 21 hats to retry/)).toBeInTheDocument();
    // The list really did empty — otherwise this passes for the wrong reason.
    expect(screen.queryByText('Why analysis is failing')).not.toBeInTheDocument();
  });

  it('says so when a retry found nothing left to queue', async () => {
    // Pressing twice is the normal way to hit this: the first press cleared
    // the failures and moved the hats to pending. Reporting it as a success
    // with a zero would read as a silent no-op.
    const user = userEvent.setup();
    vi.mocked(settingsApi.getAnalysisFailures).mockResolvedValue([OVERLOAD]);
    vi.mocked(settingsApi.retryFailedAnalysis).mockResolvedValue({
      queued: 0, worker_alive: true, job: null,
    });

    renderWithProviders(<AnalysisQueueCard />);

    await user.click(await screen.findByRole('button', { name: 'Retry 21 hats' }));
    expect(await screen.findByText(/already queued/)).toBeInTheDocument();
  });
});
