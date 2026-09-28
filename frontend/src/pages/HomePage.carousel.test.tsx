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
import { afterEach, describe, expect, it, vi, beforeEach } from 'vitest';
import { act, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../test/utils';
import { setViewportWidth } from '../test/matchMedia';
import { hatFixture } from '../test/fixtures';
import { CAROUSEL_STEP_MS, HomePage } from './HomePage';
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

/**
 * WCAG 2.2.2 (Pause, Stop, Hide): content that moves on its own must be
 * pausable, and "reduce motion" is the visitor saying so in advance. The
 * carousel advanced every five seconds with neither.
 */
describe('home carousel — moving on its own', () => {
  const original = window.matchMedia;

  function reduceMotion() {
    window.matchMedia = ((q: string) => {
      const mql = original(q);
      return q.includes('prefers-reduced-motion')
        ? { ...mql, matches: true, media: q }
        : mql;
    }) as typeof window.matchMedia;
  }

  afterEach(() => {
    window.matchMedia = original;
    vi.useRealTimers();
  });

  async function renderCarousel() {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
    setViewportWidth(PHONE);
    vi.mocked(hatsApi).listAllHats.mockResolvedValue(withPhotos(4));
    const view = renderWithProviders(<HomePage />);
    await vi.waitFor(() => expect(slides(view.container)).toHaveLength(1));
    return view;
  }

  const caption = (c: HTMLElement) => c.querySelector('.hr-cp-caption-id')?.textContent;

  async function waitAStep() {
    await act(async () => { await vi.advanceTimersByTimeAsync(CAROUSEL_STEP_MS + 100); });
  }

  it('advances by itself when motion is allowed', async () => {
    const { container } = await renderCarousel();
    const first = caption(container);
    await waitAStep();
    expect(caption(container)).not.toBe(first);
  });

  it('stays put when the browser asks for reduced motion, and offers Play', async () => {
    reduceMotion();
    const { container, getByRole } = await renderCarousel();
    const first = caption(container);
    await waitAStep();
    await waitAStep();
    expect(caption(container)).toBe(first);
    expect(getByRole('button', { name: 'Play slideshow' })).toBeInTheDocument();
  });

  it('stops when Pause is pressed', async () => {
    const { container, getByRole } = await renderCarousel();
    fireEvent.click(getByRole('button', { name: 'Pause slideshow' }));
    const first = caption(container);
    await waitAStep();
    expect(caption(container)).toBe(first);
    expect(getByRole('button', { name: 'Play slideshow' })).toBeInTheDocument();
  });

  it('holds still while the pointer is over it', async () => {
    const { container } = await renderCarousel();
    fireEvent.mouseEnter(container.querySelector('.hr-carousel')!);
    const first = caption(container);
    await waitAStep();
    expect(caption(container)).toBe(first);
  });

  it('holds still while focus is inside it', async () => {
    const { container, getByRole } = await renderCarousel();
    act(() => { getByRole('button', { name: 'Next' }).focus(); });
    const first = caption(container);
    await waitAStep();
    expect(caption(container)).toBe(first);
  });

  it('moves once Play is pressed, though the pointer and focus are on the button', async () => {
    // Pressing Play puts both "holds" on the carousel; the button must not
    // turn to "Pause" over a slideshow that is still standing still.
    reduceMotion();
    const { container, getByRole } = await renderCarousel();
    const play = getByRole('button', { name: 'Play slideshow' });
    fireEvent.mouseEnter(container.querySelector('.hr-carousel')!);
    act(() => { play.focus(); });
    fireEvent.click(play);

    const first = caption(container);
    await waitAStep();
    expect(caption(container)).not.toBe(first);
    expect(getByRole('button', { name: 'Pause slideshow' })).toBeInTheDocument();
  });
});
