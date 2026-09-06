/**
 * The home carousel shows two hats on a desktop and one on a phone.
 *
 * The count is decided in JavaScript rather than by hiding a second slide in
 * CSS, so these tests are the only thing standing between that decision and a
 * phone quietly downloading a full-size photo it never displays.
 *
 * Order is shuffled on purpose (`shuffleArray`), so nothing here asserts WHICH
 * hats appear — only how many, and that they are distinct.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { waitFor } from '@testing-library/react';
import { renderWithProviders } from '../test/utils';
import { setViewportWidth } from '../test/matchMedia';
import { hatFixture } from '../test/fixtures';
import { HomePage } from './HomePage';
import * as hatsApi from '../api/hats';
import * as casesApi from '../api/cases';
import * as roomsApi from '../api/rooms';
import * as settingsApi from '../api/settings';

vi.mock('../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    listAllHats: vi.fn()
  };
});
vi.mock('../api/cases', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    listCases: vi.fn()
  };
});
vi.mock('../api/rooms', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    listRooms: vi.fn()
  };
});
vi.mock('../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getLogo: vi.fn()
  };
});

const PHONE = 390;
const DESKTOP = 1280;

function withPhotos(count: number) {
  return Array.from({ length: count }, (_, i) =>
    hatFixture({
      id: i + 1,
      display_id: `H-${i + 1}`,
      photo_path: `hats/h${i + 1}.png`,
    })
  );
}

function slides(container: HTMLElement) {
  return container.querySelectorAll('.hr-carousel-slide');
}

beforeEach(() => {
  vi.mocked(casesApi).listCases.mockResolvedValue([]);
  vi.mocked(roomsApi).listRooms.mockResolvedValue([]);
  vi.mocked(settingsApi).getLogo.mockResolvedValue({ logo_path: null });
});

describe('home carousel', () => {
  it('shows one hat on a phone', async () => {
    setViewportWidth(PHONE);
    vi.mocked(hatsApi).listAllHats.mockResolvedValue(withPhotos(4));

    const { container } = renderWithProviders(<HomePage />);

    await waitFor(() => expect(slides(container)).toHaveLength(1));
  });

  it('shows two hats side by side on a desktop', async () => {
    setViewportWidth(DESKTOP);
    vi.mocked(hatsApi).listAllHats.mockResolvedValue(withPhotos(4));

    const { container } = renderWithProviders(<HomePage />);

    await waitFor(() => expect(slides(container)).toHaveLength(2));
  });

  it('shows two DIFFERENT hats, never the same one twice', async () => {
    setViewportWidth(DESKTOP);
    vi.mocked(hatsApi).listAllHats.mockResolvedValue(withPhotos(4));

    const { container } = renderWithProviders(<HomePage />);

    await waitFor(() => expect(slides(container)).toHaveLength(2));
    const alts = [...slides(container)].map(
      s => s.querySelector('img')?.getAttribute('alt')
    );
    expect(new Set(alts).size).toBe(2);
  });

  it('falls back to one slide on a desktop when only one hat has a photo', async () => {
    // The failure this guards: `visibleCount` of 2 against a one-hat list
    // renders the same photo in both panes, which looks like a bug rather
    // than a layout.
    setViewportWidth(DESKTOP);
    vi.mocked(hatsApi).listAllHats.mockResolvedValue([
      ...withPhotos(1),
      hatFixture({ id: 99, display_id: 'H-99', photo_path: null }),
    ]);

    const { container } = renderWithProviders(<HomePage />);

    await waitFor(() => expect(slides(container)).toHaveLength(1));
  });

  it('hides the arrows when every hat is already on screen', async () => {
    // Two hats, both visible: stepping by a screenful lands back where it
    // started, so arrows that appear to do nothing are worse than none.
    setViewportWidth(DESKTOP);
    vi.mocked(hatsApi).listAllHats.mockResolvedValue(withPhotos(2));

    const { container, queryByRole } = renderWithProviders(<HomePage />);

    await waitFor(() => expect(slides(container)).toHaveLength(2));
    expect(queryByRole('button', { name: 'Next' })).not.toBeInTheDocument();
  });

  it('keeps the arrows when there is another screenful to page to', async () => {
    setViewportWidth(DESKTOP);
    vi.mocked(hatsApi).listAllHats.mockResolvedValue(withPhotos(3));

    const { container, queryByRole } = renderWithProviders(<HomePage />);

    await waitFor(() => expect(slides(container)).toHaveLength(2));
    expect(queryByRole('button', { name: 'Next' })).toBeInTheDocument();
  });

  it('renders nothing when no hat has a photo', async () => {
    setViewportWidth(DESKTOP);
    vi.mocked(hatsApi).listAllHats.mockResolvedValue([hatFixture({ photo_path: null })]);

    const { container } = renderWithProviders(<HomePage />);

    await waitFor(() => expect(container.querySelector('.hr-carousel')).toBeNull());
  });
});
