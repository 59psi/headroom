/**
 * The Add hat save: two requests, and once the first has succeeded the hat
 * exists — so a failed photo upload must never read as "Not saved" (Save
 * again made the hat twice). And the free-text fields go out only when typed:
 * an empty construction would be stored as a real, empty answer.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router';
import { renderWithProviders } from '../test/utils';
import { hatFixture } from '../test/fixtures';
import { AddHatPage } from './AddHatPage';
import * as hatsApi from '../api/hats';
import { ApiError } from '../api/client';

vi.mock('../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()) };
});
vi.mock('../api/cases', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), listCases: vi.fn(async () => []) };
});
vi.mock('../api/rooms', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), getRoomOptions: vi.fn(async () => []) };
});
vi.mock('../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getApiKeyStatus: vi.fn(async () => ({ configured: true, source: 'database', masked: 'sk-…' })),
  };
});
// The real capture goes through a cropper canvas; the page only needs a File.
vi.mock('../components/photos/PhotoCapture', () => ({
  PhotoCapture: ({ onCapture }: { onCapture: (f: File) => void }) => (
    <button type="button" onClick={() => onCapture(new File([new Uint8Array(4)], 'h.jpg', { type: 'image/jpeg' }))}>
      pick photo
    </button>
  ),
}));

const mocked = vi.mocked(hatsApi);

function renderAdd() {
  return renderWithProviders(
    <Routes>
      <Route path="/hats/new" element={<AddHatPage />} />
      <Route path="/hats/:hatId" element={<div>hat page</div>} />
    </Routes>,
    { route: '/hats/new' },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getStyles.mockResolvedValue([{ value: 'a_game', label: 'A-Game', is_beanie: false }]);
  mocked.getSizes.mockResolvedValue([{ value: 'classic', label: 'Classic' }]);
  mocked.getConditions.mockResolvedValue([{ value: 'new', label: 'New' }]);
  mocked.getConstructions.mockResolvedValue([]);
  mocked.getCollections.mockResolvedValue([]);
  mocked.createHat.mockResolvedValue(hatFixture({ id: 100 }));
});

describe('AddHatPage — a photo that fails after the hat was created', () => {
  it('reports the hat as added, moves on to it, and never creates it twice', async () => {
    const user = userEvent.setup();
    mocked.uploadHatPhoto.mockRejectedValue(new ApiError('Photo is larger than the 25 MB limit', 413));
    renderAdd();

    await user.click(await screen.findByRole('button', { name: 'pick photo' }));
    await user.click(screen.getByRole('button', { name: 'Save hat' }));

    expect(await screen.findByText('hat page')).toBeInTheDocument();
    expect(screen.getByText(/Hat added, but its photo didn't upload \(Photo is larger than the 25 MB limit\)/))
      .toBeInTheDocument();
    expect(mocked.createHat).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Not saved/)).toBeNull();
  });
});

describe('AddHatPage — what goes out', () => {
  it('leaves construction out when nothing was typed', async () => {
    const user = userEvent.setup();
    renderAdd();

    await user.click(await screen.findByRole('button', { name: 'Save hat' }));
    await waitFor(() => expect(mocked.createHat).toHaveBeenCalled());
    expect(mocked.createHat.mock.calls[0][0]).not.toHaveProperty('construction');
  });

  it('sends construction trimmed when it was typed', async () => {
    const user = userEvent.setup();
    renderAdd();

    await user.type(await screen.findByLabelText('Construction'), '  HYDRO  ');
    await user.click(screen.getByRole('button', { name: 'Save hat' }));
    await waitFor(() => expect(mocked.createHat).toHaveBeenCalled());
    expect(mocked.createHat.mock.calls[0][0]).toMatchObject({ construction: 'HYDRO' });
  });
});
