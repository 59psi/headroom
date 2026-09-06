/**
 * A failed photo upload is SHOWN, not swallowed.
 *
 * The upload was a bare `await uploadHatPhoto()` inside `try/finally` in a
 * click handler: a 413 from the size cap or a dropped LAN re-threw into the
 * event handler, the "Uploading…" line disappeared, and nothing else changed
 * — the photo looked like it had simply not taken. Every write on the page
 * goes through `useMutation` and renders `.error` now.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { Route, Routes } from 'react-router';
import { renderWithProviders } from '../test/utils';
import { hatFixture } from '../test/fixtures';
import { HatDetailPage } from './HatDetailPage';
import * as hatsApi from '../api/hats';

vi.mock('../api/hats', () => ({
  getHat: vi.fn(),
  deleteHat: vi.fn(), uploadHatPhoto: vi.fn(), reanalyzeHat: vi.fn(), recutHat: vi.fn(),
  refreshEbayForHat: vi.fn(), undisposeHat: vi.fn(), updateHatColors: vi.fn(),
  logWear: vi.fn(), undoLatestWear: vi.fn(),
}));
vi.mock('../api/settings', () => ({
  getTagBase: vi.fn(async () => ({ base_url: 'http://h', source: 'request', example_url: 'http://h/t/h/1' })),
}));
// The real capture goes through a cropper canvas; the page only needs a File.
vi.mock('../components/photos/PhotoCapture', () => ({
  PhotoCapture: ({ onCapture }: { onCapture: (f: File) => void }) => (
    <button type="button" onClick={() => onCapture(new File([new Uint8Array(4)], 'h.jpg', { type: 'image/jpeg' }))}>
      pick photo
    </button>
  ),
}));

const mocked = vi.mocked(hatsApi);

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getHat.mockResolvedValue(hatFixture({ id: 5, photo_path: null }));
});

describe('HatDetailPage photo upload', () => {
  it('renders the failure as an alert', async () => {
    mocked.uploadHatPhoto.mockRejectedValue(new Error('Photo exceeds the 20 MB limit'));

    renderWithProviders(
      <Routes><Route path="/hats/:hatId" element={<HatDetailPage />} /></Routes>,
      { route: '/hats/5' },
    );

    fireEvent.click(await screen.findByRole('button', { name: 'pick photo' }));

    expect(await screen.findByText(/20 MB limit/)).toBeInTheDocument();
    expect(mocked.uploadHatPhoto).toHaveBeenCalledTimes(1);
  });
});
