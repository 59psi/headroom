import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { sweepProgressFixture } from '../../test/fixtures';
import { ColorwayCatalogCard } from './ColorwayCatalogCard';
import * as api from '../../api/settings';
import type { CatalogStatus } from '../../types';

vi.mock('../../api/settings', () => ({
  getColorwayStatus: vi.fn(),
  refreshColorwayCatalog: vi.fn(),
}));

const mocked = vi.mocked(api);

function status(over: Partial<CatalogStatus> = {}): CatalogStatus {
  return {
    entries: 550, models: 188, colorways: 188, last_harvest: null,
    progress: sweepProgressFixture(),
    in_flight: false,
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
      // `in_flight` is `claimed || running` server-side, so a running harvest
      // always reports both. A fixture with one and not the other describes a
      // state the API cannot return.
      in_flight: true,
      progress: sweepProgressFixture({
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
      started: true, already_running: false, detail: 'Harvest started.',
    });

    renderWithProviders(<ColorwayCatalogCard />);
    await user.click(await screen.findByRole('button', { name: /Refresh from Melin Recap/ }));

    expect(mocked.refreshColorwayCatalog).toHaveBeenCalled();
    // Once it lands, the counts on the card are the report — the old copy told
    // you to reload the page, which is what having no progress forces.
    expect(await screen.findByText(/Harvest finished/)).toBeInTheDocument();
  });

  it('says so when a harvest was already running, instead of claiming it started one', async () => {
    // The server refuses a second harvest now — two concurrent runs interleave
    // inserts of the same listing title and one dies on a UNIQUE violation.
    // The card must not treat that refusal as a start: doing so would open the
    // poll window and then announce "Harvest finished" for somebody else's run.
    const user = userEvent.setup();
    mocked.getColorwayStatus.mockResolvedValue(status());
    mocked.refreshColorwayCatalog.mockResolvedValue({
      started: false, already_running: true, detail: 'Already running.',
    });

    renderWithProviders(<ColorwayCatalogCard />);
    await user.click(await screen.findByRole('button', { name: /Refresh from Melin Recap/ }));

    expect(await screen.findByText(/Already running/)).toBeInTheDocument();
    expect(screen.queryByText(/Harvest finished/)).not.toBeInTheDocument();
  });

  it('surfaces a harvest that failed, after it has stopped', async () => {
    mocked.getColorwayStatus.mockResolvedValue(status({
      progress: sweepProgressFixture({
        running: false, error: 'Melin Recap query 429',
        finished_at: new Date().toISOString(),
      }),
    }));

    renderWithProviders(<ColorwayCatalogCard />);
    expect(await screen.findByText(/Melin Recap query 429/)).toBeInTheDocument();
  });

  it('refuses a second press during the gap before the sweep starts running', async () => {
    // The window this exists for: the slot is claimed synchronously in the
    // request, `progress.begin()` runs inside the background task, so there is
    // a moment where a harvest is definitely queued and `running` is still
    // false. The card used to bridge it with a 30-second wall-clock timer,
    // which was both a guess and purely local — a harvest started on a phone
    // left this button enabled, and the next press was refused with nothing on
    // screen having said why.
    mocked.getColorwayStatus.mockResolvedValue(status({
      in_flight: true,
      progress: sweepProgressFixture({ running: false }),
    }));

    renderWithProviders(<ColorwayCatalogCard />);

    const button = await screen.findByRole('button', { name: /harvesting/i });
    expect(button).toBeDisabled();
  });
});
