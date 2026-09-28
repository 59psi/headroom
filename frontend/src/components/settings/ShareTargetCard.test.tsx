import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { ShareTargetCard } from './ShareTargetCard';
import * as clipboard from '../../lib/clipboard';

vi.mock('../../lib/clipboard', () => ({ copyText: vi.fn(async () => true) }));
vi.mock('../../api/hats', () => ({
  getStyles: vi.fn(async () => [{ value: 'a_game', label: 'A-Game', is_beanie: false }]),
  getSizes: vi.fn(async () => [{ value: 'classic', label: 'Classic' }]),
  getConditions: vi.fn(async () => [{ value: 'new', label: 'New' }]),
}));

const copyText = vi.mocked(clipboard.copyText);

beforeEach(() => {
  vi.clearAllMocks();
  copyText.mockResolvedValue(true);
});

afterEach(() => { vi.restoreAllMocks(); });

describe('ShareTargetCard', () => {
  it('keeps the whole iOS Shortcut recipe, step for step', () => {
    renderWithProviders(<ShareTargetCard />);

    expect(screen.getByRole('button', { name: 'iPhone & iPad' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('textbox', { name: 'Import URL' }))
      .toHaveValue(`${window.location.origin}/api/hats/import`);
    for (const text of ['POST', 'Authorization', 'Bearer YOUR-API-TOKEN', 'Form', 'photos', 'File']) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    expect(screen.getByText('Shortcut Input')).toBeInTheDocument();
    expect(screen.getByText(/Name it “Add to Headroom”/)).toBeInTheDocument();
    // Where the token lives, as a link to that tab rather than directions to it.
    expect(screen.getByRole('link', { name: 'Account' })).toHaveAttribute('href', '/settings?tab=device');
  });

  it('switches to the Android instructions', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ShareTargetCard />);

    await user.click(screen.getByRole('button', { name: 'Android' }));

    expect(screen.getByRole('button', { name: 'Android' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText(/install Headroom as a PWA/)).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Import URL' })).not.toBeInTheDocument();
  });

  it('opens on the Android instructions on an Android phone', () => {
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(
      'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/140.0 Mobile Safari/537.36',
    );
    renderWithProviders(<ShareTargetCard />);

    expect(screen.getByRole('button', { name: 'Android' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText(/install Headroom as a PWA/)).toBeInTheDocument();
  });

  it('copies the import URL', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ShareTargetCard />);

    await user.click(screen.getByRole('button', { name: 'Copy the import URL' }));

    // The field goes along as the plain-http fallback.
    expect(copyText).toHaveBeenCalledWith(
      `${window.location.origin}/api/hats/import`,
      screen.getByRole('textbox', { name: 'Import URL' }),
    );
    expect(await screen.findByRole('button', { name: 'Copied the import URL' })).toBeInTheDocument();
  });

  it('states the bulk-import defaults in words, not stored values, on either platform', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ShareTargetCard />);
    expect(await screen.findByText(/style: A-Game · size: Classic · condition: New\b/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Android' }));
    expect(screen.getByText(/style: A-Game · size: Classic ·/)).toBeInTheDocument();
  });

  it('leads with a status and folds the background under "How this works"', () => {
    renderWithProviders(<ShareTargetCard />);
    expect(screen.getByText('Per phone', { selector: '.hr-pill' })).toBeInTheDocument();
    expect(screen.getByText('How this works')).toBeInTheDocument();
  });
});
