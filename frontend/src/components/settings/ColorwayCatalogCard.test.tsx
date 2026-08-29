import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { ColorwayCatalogCard } from './ColorwayCatalogCard';
import * as api from '../../api/settings';
import type { CatalogStatus, SweepProgress } from '../../types';

vi.mock('../../api/settings', () => ({
  getColorwayStatus: vi.fn(),
  refreshColorwayCatalog: vi.fn(),
}));

const mocked = vi.mocked(api);

function progress(over: Partial<SweepProgress> = {}): SweepProgress {
  return {
    running: false, done: 0, total: 0, label: null,
    started_at: null, finished_at: null, error: null, pct: 0,
    ...over,
  };
}

function status(over: Partial<CatalogStatus> = {}): CatalogStatus {
  return {
    entries: 550, models: 188, colorways: 188, last_harvest: null,
    progress: progress(),
    ...over,
  };
}

beforeEach(() => { vi.clearAllMocks(); });

describe('ColorwayCatalogCard — live harvest progress', () => {
  it('shows which category it is on while harvesting', async () => {
    // This endpoint answers 202 and runs in the background, so before this its
    // only trace was a log line — from this page a working harvest and a dead
    // button looked exactly alike, and the card just said "reload in a minute".
    mocked.getColorwayStatus.mockResolvedValue(status({
      progress: progress({
        running: true, done: 4, total: 9, pct: 44, label: 'odysea',
        started_at: new Date().toISOString(),
      }),
    }));

    renderWithProviders(<ColorwayCatalogCard />);

    const bar = await screen.findByRole('progressbar', { name: 'Sweep progress' });
    expect(bar).toHaveAttribute('aria-valuenow', '4');
    expect(bar).toHaveAttribute('aria-valuemax', '9');
    expect(screen.getByText('4 / 9')).toBeInTheDocument();
    expect(screen.getByText('odysea')).toBeInTheDocument();
  });

  it('shows nothing while idle', async () => {
    mocked.getColorwayStatus.mockResolvedValue(status());
    renderWithProviders(<ColorwayCatalogCard />);
    await screen.findByRole('button', { name: /Refresh from Melin Recap/ });
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('starts the harvest and begins watching for it', async () => {
    const user = userEvent.setup();
    mocked.getColorwayStatus.mockResolvedValue(status());
    mocked.refreshColorwayCatalog.mockResolvedValue({
      started: true, detail: 'Harvest started.',
    });

    renderWithProviders(<ColorwayCatalogCard />);
    await user.click(await screen.findByRole('button', { name: /Refresh from Melin Recap/ }));

    expect(mocked.refreshColorwayCatalog).toHaveBeenCalled();
    // Once it lands, the counts on the card are the report — the old copy told
    // you to reload the page, which is what having no progress forces.
    expect(await screen.findByText(/Harvest finished/)).toBeInTheDocument();
  });

  it('surfaces a harvest that failed, after it has stopped', async () => {
    mocked.getColorwayStatus.mockResolvedValue(status({
      progress: progress({
        running: false, error: 'Melin Recap query 429',
        finished_at: new Date().toISOString(),
      }),
    }));

    renderWithProviders(<ColorwayCatalogCard />);
    expect(await screen.findByText(/Melin Recap query 429/)).toBeInTheDocument();
  });
});
