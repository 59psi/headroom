/**
 * Home while loading, after a failure, and with part of it missing.
 *
 * The page used to be a bare spinner until everything arrived and a sentence
 * telling you to reload when anything failed. Now the hero (and its two
 * actions) renders at once, the valuation card holds its shape while the
 * numbers load, a failure retries in place, and an unknown room count is a
 * dash rather than a confident zero.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../test/utils';
import { caseFixture, hatFixture } from '../test/fixtures';
import { HomePage } from './HomePage';
import * as hatsApi from '../api/hats';
import * as casesApi from '../api/cases';
import * as roomsApi from '../api/rooms';
import * as settingsApi from '../api/settings';

vi.mock('../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), listAllHats: vi.fn() };
});
vi.mock('../api/cases', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), listCases: vi.fn() };
});
vi.mock('../api/rooms', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), listRooms: vi.fn() };
});
vi.mock('../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), getLogo: vi.fn() };
});

const hats = vi.mocked(hatsApi);
const cases = vi.mocked(casesApi);
const rooms = vi.mocked(roomsApi);

beforeEach(() => {
  vi.clearAllMocks();
  hats.listAllHats.mockResolvedValue([hatFixture({ estimated_new_price: 100 })]);
  cases.listCases.mockResolvedValue([caseFixture()]);
  rooms.listRooms.mockResolvedValue([]);
  vi.mocked(settingsApi).getLogo.mockResolvedValue({ logo_path: null });
});

describe('HomePage states', () => {
  it('shows the hero and its actions at once, and the valuation card in outline while loading', () => {
    hats.listAllHats.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<HomePage />);

    expect(screen.getByRole('link', { name: 'Add hat' })).toHaveAttribute('href', '/hats/new');
    expect(screen.getByRole('link', { name: 'Add case' })).toHaveAttribute('href', '/cases/new');
    expect(screen.getByRole('heading', { name: 'Valuation overview' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/loading your collection/i);
    // No figure is shown before there is one to show.
    expect(screen.queryByText('$0')).toBeNull();
  });

  it('retries a failed load in place instead of asking for a reload', async () => {
    const user = userEvent.setup();
    hats.listAllHats.mockRejectedValueOnce(new Error('500'));
    renderWithProviders(<HomePage />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn.t load your collection/i);
    await user.click(screen.getByRole('button', { name: /try again/i }));

    const rail = await screen.findByRole('navigation', { name: /collection summary/i });
    expect(within(rail).getByRole('link', { name: /1\s*hats/i })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows an unknown room count as a dash, not zero', async () => {
    rooms.listRooms.mockRejectedValue(new Error('500'));
    renderWithProviders(<HomePage />);

    const rail = await screen.findByRole('navigation', { name: /collection summary/i });
    expect(within(rail).getByRole('link', { name: /rooms/i })).toHaveTextContent('–Rooms');
    expect(within(rail).getByRole('alert')).toHaveTextContent(/some of the dashboard could not load/i);
  });

  it('keeps one primary action on the page', async () => {
    renderWithProviders(<HomePage />);
    await screen.findByRole('navigation', { name: /collection summary/i });

    // "Add hat" glows; "Add case" and "Full breakdown" are secondary.
    const primaries = document.querySelectorAll('.btn-primary');
    expect([...primaries].map(el => el.textContent)).toEqual(['Add hat']);
  });
});
