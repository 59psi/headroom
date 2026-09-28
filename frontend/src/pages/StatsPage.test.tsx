/**
 * Stats: grouped, jumpable, and honest while loading.
 *
 * Twenty-odd chart cards are now grouped under five section headings with a
 * jump bar; a jump moves focus to the section, not just the scroll position.
 * The page waits for the disposed hats too — the Realized tile read "$0 · 0
 * sold" until they arrived. And its color bars link with `?hex=`, the key the
 * Search page reads a color search from.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../test/utils';
import { caseFixture, hatFixture } from '../test/fixtures';
import { StatsPage } from './StatsPage';
import * as hatsApi from '../api/hats';
import * as casesApi from '../api/cases';
import * as roomsApi from '../api/rooms';

vi.mock('../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    listAllHats: vi.fn(),
    listDisposedHats: vi.fn(),
  };
});
vi.mock('../api/cases', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), listCases: vi.fn() };
});
vi.mock('../api/rooms', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), listRooms: vi.fn() };
});

const hats = vi.mocked(hatsApi);

beforeEach(() => {
  vi.clearAllMocks();
  hats.listAllHats.mockResolvedValue([
    hatFixture({
      id: 1,
      colors: [{ color_name: 'ocean', general_color: 'blue', hex_value: '#0a84ff', dominance_rank: 1 }],
    }),
  ]);
  hats.listDisposedHats.mockResolvedValue([]);
  vi.mocked(casesApi).listCases.mockResolvedValue([caseFixture()]);
  vi.mocked(roomsApi).listRooms.mockResolvedValue([]);
});

describe('StatsPage', () => {
  it('waits for the disposed hats before showing any money figure', async () => {
    hats.listDisposedHats.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<StatsPage />);

    expect(await screen.findByRole('heading', { name: 'The collection' })).toBeInTheDocument();
    expect(screen.getAllByRole('status')[0]).toHaveTextContent(/loading stats/i);
    expect(screen.queryByText('Realized')).toBeNull();
  });

  it('groups the cards under section headings', async () => {
    renderWithProviders(<StatsPage />);

    expect(await screen.findByRole('heading', { level: 2, name: 'Composition' })).toBeInTheDocument();
    const composition = screen.getByRole('region', { name: 'Composition' });
    expect(within(composition).getByRole('heading', { level: 3, name: 'By style' })).toBeInTheDocument();
  });

  it('moves focus to the section a jump link names', async () => {
    const user = userEvent.setup();
    renderWithProviders(<StatsPage />);
    const nav = await screen.findByRole('navigation', { name: /stats sections/i });

    await user.click(within(nav).getByRole('link', { name: 'Leaderboards' }));

    expect(screen.getByRole('heading', { level: 2, name: 'Leaderboards' })).toHaveFocus();
  });

  it('links a color bar to a color search by hex', async () => {
    renderWithProviders(<StatsPage />);

    const bar = await screen.findByRole('link', { name: /blue/i });
    expect(bar).toHaveAttribute('href', '/search?hex=%230a84ff');
  });

  it('retries a failed load in place', async () => {
    const user = userEvent.setup();
    hats.listAllHats.mockRejectedValueOnce(new Error('500'));
    renderWithProviders(<StatsPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/no charts are shown/i);
    await user.click(screen.getByRole('button', { name: /try again/i }));

    expect(await screen.findByRole('heading', { name: 'Composition' })).toBeInTheDocument();
  });
});
