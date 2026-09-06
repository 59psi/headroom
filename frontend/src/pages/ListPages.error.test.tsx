/**
 * A failed fetch is an error, not an empty collection.
 *
 * Home, Valuation and Stats each carry the paragraph explaining why (`?? []`
 * turns a 500 into "$0 across 0 hats"); the two list pages still rendered a
 * failed load as "No hats to display — Add First Hat". A confident wrong answer
 * with a call to action is worse than a spinner.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../test/utils';
import { HatsPage } from './HatsPage';
import { CasesPage } from './CasesPage';

vi.mock('../api/hats', () => ({
  listAllHats: vi.fn(async () => { throw new Error('500'); }),
  getStyles: vi.fn(async () => []),
  getSizes: vi.fn(async () => []),
  getConditions: vi.fn(async () => []),
  getConstructions: vi.fn(async () => []),
}));
vi.mock('../api/cases', () => ({
  listCases: vi.fn(async () => { throw new Error('500'); }),
}));
vi.mock('../api/rooms', () => ({
  getRoomOptions: vi.fn(async () => []),
}));

describe('list pages on a failed fetch', () => {
  it('Hats shows an error, not "Add First Hat"', async () => {
    renderWithProviders(<HatsPage />, { route: '/hats' });

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn.t load your hats/i);
    expect(screen.queryByRole('link', { name: /add first hat/i })).toBeNull();
  });

  it('Cases shows an error, not "Create First Case"', async () => {
    renderWithProviders(<CasesPage />, { route: '/cases' });

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn.t load your cases/i);
    expect(screen.queryByRole('link', { name: /create first case/i })).toBeNull();
  });
});
