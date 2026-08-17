import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import { AnalysisQueueCard } from './AnalysisQueueCard';
import * as settingsApi from '../../api/settings';
import type { AnalysisQueueStatus } from '../../api/settings';

vi.mock('../../api/settings', () => ({
  getAnalysisQueue: vi.fn(),
  reanalyzeAll: vi.fn(),
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
