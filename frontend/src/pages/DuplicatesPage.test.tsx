/**
 * Duplicates: each group's confidence as a word, not only a color, and a
 * failed check that can be retried where it failed.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../test/utils';
import { DuplicatesPage } from './DuplicatesPage';
import * as searchApi from '../api/search';
import type { DuplicateGroupRead, SearchResult } from '../types';

vi.mock('../api/search', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), findDuplicates: vi.fn() };
});

const mocked = vi.mocked(searchApi);

function hat(id: number): SearchResult {
  return {
    id, display_id: `A-001-0${id}`, case_display_id: 'A-001', photo_path: null, thumb_path: null,
    style: 'a_game', condition: 'new', size: 'classic', is_beanie: false,
    brand: 'melin', model_name: 'A-Game', construction: null, colorway: null, colors: [],
    room_id: 1, room_name: 'Study',
  };
}

const GROUPS: DuplicateGroupRead[] = [
  { key: 'g1', confidence: 'exact', label: 'A-Game · Classic · Black', hats: [hat(1), hat(2)] },
  { key: 'g2', confidence: 'likely', label: 'Odysea · Classic', hats: [hat(3), hat(4)] },
];

beforeEach(() => {
  vi.clearAllMocks();
  mocked.findDuplicates.mockResolvedValue(GROUPS);
});

describe('DuplicatesPage', () => {
  it('titles each group and states its confidence in words', async () => {
    renderWithProviders(<DuplicatesPage />);

    const exact = await screen.findByRole('region', { name: 'A-Game · Classic · Black' });
    expect(within(exact).getByText('Exact match')).toHaveAttribute('title', 'Every identity field matches');
    const likely = screen.getByRole('region', { name: 'Odysea · Classic' });
    expect(within(likely).getByText('Likely')).toBeInTheDocument();
    expect(within(exact).getAllByRole('link')).toHaveLength(2);
  });

  it('says so plainly when there is nothing to review', async () => {
    mocked.findDuplicates.mockResolvedValue([]);
    renderWithProviders(<DuplicatesPage />);
    expect(await screen.findByText('No duplicates found')).toBeInTheDocument();
  });

  it('retries a failed check in place', async () => {
    const user = userEvent.setup();
    mocked.findDuplicates.mockRejectedValueOnce(new Error('500'));
    renderWithProviders(<DuplicatesPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn.t check for duplicates/i);
    await user.click(screen.getByRole('button', { name: /try again/i }));

    expect(await screen.findByRole('region', { name: 'Odysea · Classic' })).toBeInTheDocument();
  });
});
