/**
 * What the hat page SAYS: a failed load versus a missing hat, the purchase
 * date as the day that was entered, money in the app's one format, banners
 * that give the advice that fits whether a Claude key exists, and a page that
 * keeps polling while a re-cut is still working.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, screen, waitFor } from '@testing-library/react';
import { Route, Routes } from 'react-router';
import { renderWithProviders } from '../test/utils';
import { hatFixture } from '../test/fixtures';
import { HatDetailPage, REANALYZE_KEEPS } from './HatDetailPage';
import * as hatsApi from '../api/hats';
import * as settingsApi from '../api/settings';
import { ApiError } from '../api/client';
import type { HatRead } from '../types';

vi.mock('../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()) };
});
vi.mock('../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getTagBase: vi.fn(async () => ({ base_url: 'http://h', source: 'request', example_url: 'http://h/t/h/1' })),
  };
});

const mocked = vi.mocked(hatsApi);
const settings = vi.mocked(settingsApi);

function renderPage(hat: HatRead | Error) {
  if (hat instanceof Error) mocked.getHat.mockRejectedValue(hat);
  else mocked.getHat.mockResolvedValue(hat);
  return renderWithProviders(
    <Routes><Route path="/hats/:hatId" element={<HatDetailPage />} /></Routes>,
    { route: '/hats/5' },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  settings.getApiKeyStatus.mockResolvedValue({ configured: true, source: 'database', masked: 'sk-…abcd' });
});

describe('HatDetailPage — a failed load is not a missing hat', () => {
  it('says the load failed, with the reason, when the server errors', async () => {
    renderPage(new ApiError('database is locked', 500));

    expect(await screen.findByRole('alert')).toHaveTextContent('database is locked');
    expect(screen.getByText(/Could not load this hat/)).toBeInTheDocument();
    expect(screen.queryByText('Hat not found')).toBeNull();
  });

  it('says "not found" only for a 404', async () => {
    renderPage(new ApiError('Hat not found', 404));
    expect(await screen.findByText('Hat not found')).toBeInTheDocument();
  });
});

describe('HatDetailPage — the Paid tile', () => {
  let tz: string | undefined;
  beforeEach(() => { tz = process.env.TZ; });
  afterEach(() => { process.env.TZ = tz; });

  it('prints the purchase date that was entered, west of Greenwich too', async () => {
    // The form stores midnight of the chosen day; the API answers it as UTC
    // midnight. Formatted as an instant, that is the 14th in Los Angeles.
    process.env.TZ = 'America/Los_Angeles';
    renderPage(hatFixture({ purchase_price: 79, purchased_at: '2024-03-15T00:00:00Z' }));

    const expected = new Date(2024, 2, 15).toLocaleDateString();
    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(screen.queryByText(new Date(2024, 2, 14).toLocaleDateString())).toBeNull();
  });

  it('says the DATE is what is missing, not the price', async () => {
    renderPage(hatFixture({ purchase_price: 69, purchased_at: null }));
    expect(await screen.findByText('date not recorded')).toBeInTheDocument();
  });
});

describe('HatDetailPage — money in the app’s one format', () => {
  it('groups a cost per wear and keeps its cents', async () => {
    renderPage(hatFixture({ purchase_price: 2469, wear_count: 2 }));
    expect(await screen.findByText(/\$1,234\.50\/wear/)).toBeInTheDocument();
  });

  it('shows no cost per wear for a hat that cost nothing on record', async () => {
    // `costOf` — the Stats leaderboard's rule — treats $0 as no price, so
    // the hat page does not show a figure that page leaves out.
    renderPage(hatFixture({ purchase_price: 0, wear_count: 3 }));
    expect(await screen.findByText('3×')).toBeInTheDocument();
    expect(screen.queryByText(/\/wear/)).toBeNull();
  });

  it('shows a sale price to the cent', async () => {
    renderPage(hatFixture({
      disposed_at: '2026-09-01T00:00:00Z', disposed_via: 'sold', disposed_price: 45.5,
    }));
    expect(await screen.findByText('$45.50')).toBeInTheDocument();
  });

  it('prints the price tiles with thousands separators and no cents', async () => {
    renderPage(hatFixture({ estimated_new_price: 1250.4 }));
    expect(await screen.findByText('$1,250')).toBeInTheDocument();
  });
});

describe('HatDetailPage — analysis banners follow whether a key exists', () => {
  /** The banners' way to the key — not the tag card's Settings link. */
  const keyLinks = () => screen.queryAllByRole('link', { name: 'Settings' })
    .filter(a => a.getAttribute('href') === '/settings?tab=analysis');

  it('points a keyless fallback hat at Settings even though it carries a reason — once', async () => {
    // The server's text for a keyless hat carries its own "add a key"
    // sentence (`fallback_message`); printed as the "Why" beside the banner's
    // linked one, the same advice read twice.
    settings.getApiKeyStatus.mockResolvedValue({ configured: false, source: null, masked: null });
    renderPage(hatFixture({
      analysis_status: 'fallback',
      analysis_error: 'No Anthropic API key configured — basic fallback applied (colors from photo cutout). Add a Claude API key in Settings and Reanalyze for full identification.',
    }));

    await waitFor(() => expect(keyLinks()).toHaveLength(1));
    const banner = keyLinks()[0].closest('.alert')!;
    expect(banner.textContent!.match(/add (a Claude API key|one)/gi)).toHaveLength(1);
    expect(banner).not.toHaveTextContent('Why:');
  });

  it('does not tell someone WITH a key to add one', async () => {
    renderPage(hatFixture({ analysis_status: 'fallback', analysis_error: 'Anthropic credit balance too low' }));

    expect(await screen.findByText(/credit balance too low/)).toBeInTheDocument();
    await waitFor(() => expect(settings.getApiKeyStatus).toHaveBeenCalled());
    expect(keyLinks()).toHaveLength(0);
  });

  it('asks for a Reanalyze, not a key, on a hat skipped before the key was added', async () => {
    renderPage(hatFixture({ analysis_status: 'skipped' }));
    expect(await screen.findByText(/Tap Reanalyze to identify it/)).toBeInTheDocument();
  });

  it('gives neither piece of advice until it knows whether a key exists', async () => {
    // Otherwise the banner said "Tap Reanalyze" and then, a moment later,
    // "configure your key" on a keyless install.
    settings.getApiKeyStatus.mockReturnValue(new Promise(() => {}));
    renderPage(hatFixture({ analysis_status: 'skipped' }));
    expect(await screen.findByText('This hat has not been analyzed yet.')).toBeInTheDocument();
    expect(screen.queryByText(/Tap Reanalyze/)).toBeNull();
    expect(keyLinks()).toHaveLength(0);
  });

  it('says what Reanalyze keeps, next to the button', async () => {
    renderPage(hatFixture({ photo_path: 'hats/5.png' }));
    const button = await screen.findByRole('button', { name: /Reanalyze/ });
    expect(button).toHaveAccessibleDescription(REANALYZE_KEEPS);
  });
});

describe('HatDetailPage — polling', () => {
  afterEach(() => vi.useRealTimers());

  it('keeps polling while a re-cut is in flight, and stops when the cutout lands', async () => {
    // A re-cut keeps the hat's status ("ok") and reports only its stage.
    // Polling on status alone left the old photo up until something else
    // happened to refetch.
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout'] });
    mocked.getHat
      .mockResolvedValueOnce(hatFixture({ analysis_status: 'ok', analysis_stage: 'cutout', photo_path: 'old.png' }))
      .mockResolvedValue(hatFixture({ analysis_status: 'ok', analysis_stage: null, photo_path: 'new.png' }));
    renderWithProviders(
      <Routes><Route path="/hats/:hatId" element={<HatDetailPage />} /></Routes>,
      { route: '/hats/5' },
    );

    await vi.waitFor(() => expect(mocked.getHat).toHaveBeenCalledTimes(1));
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    expect(mocked.getHat).toHaveBeenCalledTimes(2);

    // Settled: no stage, not pending — the polling ends.
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(mocked.getHat).toHaveBeenCalledTimes(2);
  });
});
