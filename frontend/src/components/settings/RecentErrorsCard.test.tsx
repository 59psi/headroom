import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { hatFixture } from '../../test/fixtures';
import { RecentErrorsCard } from './RecentErrorsCard';
import * as settingsApi from '../../api/settings';
import * as hatsApi from '../../api/hats';
import type { RecentError } from '../../types';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getRecentErrors: vi.fn(),
    getRecentErrorsCount: vi.fn(),
    getApiKeyStatus: vi.fn(),
  };
});

vi.mock('../../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), reanalyzeHat: vi.fn() };
});

const OVERLOADED: RecentError = {
  hat_id: 63, display_id: 'A1-2',
  analysis_error: 'Claude analysis failed: overloaded_error',
  analyzed_at: new Date(Date.now() - 3_600_000).toISOString(),
  photo_path: 'hats/63.png',
  thumb_path: 'hats/63.thumb.webp',
};
const NO_PHOTO: RecentError = {
  hat_id: 64, display_id: 'A1-3',
  analysis_error: 'Photo missing before analysis could run.',
  analyzed_at: null,
  photo_path: null,
  thumb_path: null,
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(settingsApi.getApiKeyStatus).mockResolvedValue({
    configured: true, source: 'database', masked: 'sk-an…wxyz',
  });
  vi.mocked(settingsApi.getRecentErrorsCount).mockResolvedValue({ count: 2 });
});

describe('RecentErrorsCard', () => {
  it('counts from the real total, and says when the list is only the newest', async () => {
    // The list is capped; its length alone would top out and read as the
    // whole story. The count is the same number the nav badge shows.
    vi.mocked(settingsApi.getRecentErrors).mockResolvedValue([OVERLOADED, NO_PHOTO]);
    vi.mocked(settingsApi.getRecentErrorsCount).mockResolvedValue({ count: 35 });

    renderWithProviders(<RecentErrorsCard />);

    expect(await screen.findByText('35 failed')).toBeInTheDocument();
    expect(screen.getByText('Showing the 2 most recent of 35.')).toBeInTheDocument();
  });

  it('retries one hat in place and says so', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getRecentErrors)
      .mockResolvedValueOnce([OVERLOADED])
      .mockResolvedValue([]);
    vi.mocked(hatsApi.reanalyzeHat).mockResolvedValue(
      hatFixture({ id: 63, analysis_status: 'pending' }),
    );

    renderWithProviders(<RecentErrorsCard />);
    await user.click(await screen.findByRole('button', { name: 'Retry analysis for A1-2' }));

    expect(hatsApi.reanalyzeHat).toHaveBeenCalledWith(63);
    expect(await screen.findByText('A1-2 queued for re-analysis')).toBeInTheDocument();
    // The list refetched, and the retried hat — now pending — has left it.
    expect(await screen.findByText('No analysis errors.')).toBeInTheDocument();
    expect(settingsApi.getRecentErrors).toHaveBeenCalledTimes(2);
  });

  it('does not call a retry that still failed a success', async () => {
    // With no Claude key (or the worker off) the retry runs inline and can
    // come back still carrying a failure — the fallback's own reason. The hat
    // stays on this list, so a "re-analyzed" success and a Retry button that
    // never comes back would both be claims the row next to them contradicts.
    const user = userEvent.setup();
    const STILL: RecentError = {
      ...OVERLOADED,
      analysis_error: 'Fallback only: no Anthropic API key configured.',
    };
    vi.mocked(settingsApi.getRecentErrors)
      .mockResolvedValueOnce([OVERLOADED])
      .mockResolvedValue([STILL]);
    vi.mocked(hatsApi.reanalyzeHat).mockResolvedValue(
      hatFixture({ id: 63, analysis_status: 'fallback', analysis_error: STILL.analysis_error }),
    );

    renderWithProviders(<RecentErrorsCard />);
    await user.click(await screen.findByRole('button', { name: 'Retry analysis for A1-2' }));

    expect(await screen.findByText('A1-2 re-analyzed, but it is still failing')).toBeInTheDocument();
    expect(screen.queryByText('A1-2 re-analyzed')).not.toBeInTheDocument();
    expect(await screen.findByText(/Fallback only/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry analysis for A1-2' })).toBeEnabled();
  });

  it('shows the exact time of a failure, not only how long ago', async () => {
    // "45 days ago" is all a phone could read before: the exact time was in a
    // hover tooltip, and no other screen shows when analysis last ran.
    const at = '2026-08-12T14:03:09Z';
    vi.mocked(settingsApi.getRecentErrors).mockResolvedValue([{ ...OVERLOADED, analyzed_at: at }]);

    renderWithProviders(<RecentErrorsCard />);

    expect(await screen.findByText(new Date(at).toLocaleString(), { exact: false })).toBeInTheDocument();
  });

  it("keeps a failed retry's reason on its own row", async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getRecentErrors).mockResolvedValue([OVERLOADED]);
    vi.mocked(hatsApi.reanalyzeHat).mockRejectedValue(new Error('Photo file missing on disk'));

    renderWithProviders(<RecentErrorsCard />);
    await user.click(await screen.findByRole('button', { name: 'Retry analysis for A1-2' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Could not retry A1-2');
    expect(alert).toHaveTextContent('Photo file missing on disk');
    // Still retryable — the button came back rather than sticking on "Retrying…".
    expect(screen.getByRole('button', { name: 'Retry analysis for A1-2' })).toBeEnabled();
  });

  it('offers no retry for a hat with no photo to analyze', async () => {
    vi.mocked(settingsApi.getRecentErrors).mockResolvedValue([NO_PHOTO]);

    renderWithProviders(<RecentErrorsCard />);

    expect(await screen.findByText('A1-3')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Retry analysis/ })).not.toBeInTheDocument();
  });

  it('shows the small tile, not the full cutout, and names a caseless hat the way other screens do', async () => {
    vi.mocked(settingsApi.getRecentErrors).mockResolvedValue([
      OVERLOADED, { ...NO_PHOTO, hat_id: 70, display_id: null },
    ]);

    const { container } = renderWithProviders(<RecentErrorsCard />);

    expect(await screen.findByText('Hat #70')).toBeInTheDocument();
    expect(container.querySelector('img.hr-an-err-thumb')).toHaveAttribute('src', '/uploads/hats/63.thumb.webp');
  });

  it("a row's retry refreshes the nav badge and the queue card, not only this list", async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getRecentErrors).mockResolvedValue([OVERLOADED]);
    vi.mocked(hatsApi.reanalyzeHat).mockResolvedValue(hatFixture({ id: 63, analysis_status: 'pending' }));

    const { client } = renderWithProviders(<RecentErrorsCard />);
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    await user.click(await screen.findByRole('button', { name: 'Retry analysis for A1-2' }));
    await screen.findByText('A1-2 queued for re-analysis');

    const keys = invalidate.mock.calls.map(([f]) => JSON.stringify(f?.queryKey));
    for (const k of [
      ['admin', 'recent-errors'], ['admin', 'recent-errors-count'],
      ['admin', 'analysis-queue'], ['admin', 'analysis-failures'], ['hat', 63],
    ]) expect(keys).toContain(JSON.stringify(k));
  });

  it('refreshes the list and the nav badge together', async () => {
    // Sibling keys: refreshing only the list left the badge disagreeing.
    const user = userEvent.setup();
    vi.mocked(settingsApi.getRecentErrors).mockResolvedValue([]);

    renderWithProviders(<RecentErrorsCard />);
    await user.click(await screen.findByRole('button', { name: 'Refresh' }));

    await vi.waitFor(() => {
      expect(settingsApi.getRecentErrors).toHaveBeenCalledTimes(2);
      expect(settingsApi.getRecentErrorsCount).toHaveBeenCalledTimes(2);
    });
  });

  it('follows the nav badge: a new failure there brings its row here', async () => {
    // The header pill reads the badge's count, which polls; the list did not.
    // A hat failing while the page was open left the pill saying "1 failed"
    // over a body saying "No analysis errors." until something else refetched.
    vi.mocked(settingsApi.getRecentErrors).mockResolvedValueOnce([]).mockResolvedValue([OVERLOADED]);
    vi.mocked(settingsApi.getRecentErrorsCount).mockResolvedValueOnce({ count: 0 }).mockResolvedValue({ count: 1 });

    const { client } = renderWithProviders(<RecentErrorsCard />);
    expect(await screen.findByText('No analysis errors.')).toBeInTheDocument();
    expect(screen.getByText('None')).toBeInTheDocument();

    // The badge's once-a-minute poll, as far as the cache can tell.
    await client.refetchQueries({ queryKey: ['admin', 'recent-errors-count'] });

    expect(await screen.findByText('A1-2')).toBeInTheDocument();
    expect(screen.getByText('1 failed')).toBeInTheDocument();
    expect(screen.queryByText('No analysis errors.')).not.toBeInTheDocument();
  });

  it('only tells you to add a key once it knows there is none', async () => {
    vi.mocked(settingsApi.getRecentErrors).mockResolvedValue([]);
    vi.mocked(settingsApi.getRecentErrorsCount).mockResolvedValue({ count: 0 });
    vi.mocked(settingsApi.getApiKeyStatus).mockReturnValue(new Promise(() => {}));

    renderWithProviders(<RecentErrorsCard />);

    expect(await screen.findByText('No analysis errors.')).toBeInTheDocument();
    expect(screen.getByText('None')).toBeInTheDocument();
    expect(screen.queryByText(/Configure a Claude API key/)).not.toBeInTheDocument();
  });

  it('points at the key when there is none', async () => {
    vi.mocked(settingsApi.getRecentErrors).mockResolvedValue([]);
    vi.mocked(settingsApi.getRecentErrorsCount).mockResolvedValue({ count: 0 });
    vi.mocked(settingsApi.getApiKeyStatus).mockResolvedValue({ configured: false, source: null, masked: null });

    renderWithProviders(<RecentErrorsCard />);

    expect(await screen.findByText(/Configure a Claude API key to start analyzing/)).toBeInTheDocument();
  });
});
