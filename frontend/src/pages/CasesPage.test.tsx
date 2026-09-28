/**
 * The Cases tab: placeholder tiles while loading, filters that live in the
 * URL and count what they would show, and an empty result that offers the
 * way out rather than a dead end.
 *
 * The failed-fetch case ("an error, not 'Create First Case'") is covered in
 * `ListPages.error.test.tsx` alongside the Hats tab.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../test/utils';
import { caseFixture } from '../test/fixtures';
import { CasesPage } from './CasesPage';
import * as casesApi from '../api/cases';
import * as roomsApi from '../api/rooms';

vi.mock('../api/cases', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), listCases: vi.fn() };
});
vi.mock('../api/rooms', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), getRoomOptions: vi.fn() };
});

const cases = vi.mocked(casesApi);
const rooms = vi.mocked(roomsApi);

const ALL = [
  caseFixture({ id: 1, display_id: 'A-001', case_type: 'archive', room_id: 1, room_name: 'Study', hat_count: 2, regular_count: 2 }),
  caseFixture({ id: 2, display_id: 'A-002', case_type: 'archive', room_id: 2, room_name: 'Den', hat_count: 1, regular_count: 1 }),
  caseFixture({ id: 3, display_id: 'D-001', case_type: 'daily_wear', room_id: 2, room_name: 'Den' }),
];

beforeEach(() => {
  vi.clearAllMocks();
  cases.listCases.mockResolvedValue(ALL);
  rooms.getRoomOptions.mockResolvedValue([{ value: 1, label: 'Study' }, { value: 2, label: 'Den' }]);
});

/** Case ids on screen, in order. */
function shownIds() {
  return [...document.querySelectorAll('.hr-case-tile-id')].map(el => el.textContent);
}

describe('CasesPage', () => {
  it('holds the grid shape while loading instead of a spinner', () => {
    cases.listCases.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<CasesPage />, { route: '/cases' });

    expect(screen.getByRole('heading', { level: 1, name: 'Cases' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Loading cases…');
    // The filters are usable before the data arrives.
    expect(screen.getByRole('group', { name: 'Case type' })).toBeInTheDocument();
  });

  it('counts each type segment, and filters in place', async () => {
    const user = userEvent.setup();
    renderWithProviders(<CasesPage />, { route: '/cases' });

    await screen.findByText('A-001');
    expect(screen.getByText('3 cases · 3 hats')).toBeInTheDocument();
    const archive = screen.getByRole('button', { name: /^Archive/ });
    expect(archive).toHaveTextContent('Archive2');
    expect(archive).toHaveAttribute('aria-pressed', 'false');

    await user.click(archive);
    expect(archive).toHaveAttribute('aria-pressed', 'true');
    expect(shownIds()).toEqual(['A-001', 'A-002']);
  });

  it('reads the room filter from the URL, and counts within it', async () => {
    renderWithProviders(<CasesPage />, { route: '/cases?room=2' });

    await screen.findByText('A-002');
    expect(shownIds()).toEqual(['A-002', 'D-001']);
    expect(screen.getByRole('combobox', { name: 'Room' })).toHaveValue('2');
    const seg = screen.getByRole('group', { name: 'Case type' });
    expect(within(seg).getByRole('button', { name: /^All/ })).toHaveTextContent('All2');
    expect(within(seg).getByRole('button', { name: /^Daily wear/ })).toHaveTextContent('Daily wear1');
  });

  it('ignores a room id from a stale link rather than filtering to nothing', async () => {
    renderWithProviders(<CasesPage />, { route: '/cases?room=99' });

    await screen.findByRole('option', { name: 'Den' });
    await screen.findByText('A-001');
    expect(shownIds()).toEqual(['A-001', 'A-002', 'D-001']);
    expect(screen.getByRole('combobox', { name: 'Room' })).toHaveValue('');
  });

  it('offers to clear filters that match nothing', async () => {
    const user = userEvent.setup();
    renderWithProviders(<CasesPage />, { route: '/cases?type=daily_wear&room=1' });

    expect(await screen.findByText('No matching cases')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));

    expect(shownIds()).toEqual(['A-001', 'A-002', 'D-001']);
    expect(screen.getByRole('button', { name: /^All/ })).toHaveAttribute('aria-pressed', 'true');
  });

  it('names the filter that matched nothing, not always both', async () => {
    cases.listCases.mockResolvedValue(ALL.filter(c => c.case_type === 'archive'));
    renderWithProviders(<CasesPage />, { route: '/cases?type=daily_wear' });

    expect(await screen.findByText('No matching cases')).toBeInTheDocument();
    expect(screen.getByText('No daily wear cases yet.')).toBeInTheDocument();
    expect(screen.queryByText(/room/i, { selector: '.hr-cr-empty-text' })).not.toBeInTheDocument();
  });

  it('offers to create the first case when there are none', async () => {
    cases.listCases.mockResolvedValue([]);
    renderWithProviders(<CasesPage />, { route: '/cases' });

    expect(await screen.findByRole('link', { name: 'Create first case' })).toHaveAttribute('href', '/cases/new');
  });

  it('retries a failed load in place instead of asking for a reload', async () => {
    const user = userEvent.setup();
    cases.listCases.mockRejectedValueOnce(new Error('database is locked'));
    renderWithProviders(<CasesPage />, { route: '/cases' });

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('database is locked');
    expect(alert).not.toHaveTextContent(/reload/i);
    await user.click(within(alert).getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('A-001')).toBeInTheDocument();
  });

  it('says so when the room filter could not load, rather than offering only "All rooms"', async () => {
    rooms.getRoomOptions.mockRejectedValue(new Error('database is locked'));
    renderWithProviders(<CasesPage />, { route: '/cases' });

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the room filter — database is locked');
    expect(screen.getByText('A-001')).toBeInTheDocument();
  });
});
