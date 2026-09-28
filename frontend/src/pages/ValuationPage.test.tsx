/**
 * Valuation: the breakdowns as tables, the method one tap away, and no total
 * shown until every part of it has arrived.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import { renderWithProviders } from '../test/utils';
import { caseFixture, hatFixture } from '../test/fixtures';
import { ValuationPage } from './ValuationPage';
import * as hatsApi from '../api/hats';
import * as casesApi from '../api/cases';

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

const hats = vi.mocked(hatsApi);
const cases = vi.mocked(casesApi);

beforeEach(() => {
  vi.clearAllMocks();
  hats.listAllHats.mockResolvedValue([
    // Manual price: valued at exactly what was entered.
    hatFixture({ id: 1, brand: 'melin', purchase_price: 80, resale_price: 120, resale_price_scope: 'manual' }),
    hatFixture({ id: 2, brand: 'Other' }),
  ]);
  hats.listDisposedHats.mockResolvedValue([]);
  cases.listCases.mockResolvedValue([caseFixture({ retail_price: 49 })]);
});

describe('ValuationPage', () => {
  it('holds every total until the cases have arrived too', async () => {
    cases.listCases.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<ValuationPage />);

    expect(await screen.findByRole('heading', { name: 'Collection totals' })).toBeInTheDocument();
    expect(screen.getAllByRole('status')[0]).toHaveTextContent(/loading the valuation/i);
    expect(screen.queryByText(/everything, together/i)).toBeNull();
  });

  it('lays each breakdown out as a table: what, how many, paid, worth', async () => {
    renderWithProviders(<ValuationPage />);

    const card = await screen.findByRole('region', { name: 'By brand' });
    const table = within(card).getByRole('table');
    expect(within(table).getAllByRole('columnheader').map(h => h.textContent)).toEqual(['Brand', 'Hats', 'Paid', 'Worth']);

    const melin = within(table).getByRole('rowheader', { name: 'melin' }).closest('tr')!;
    expect(within(melin).getAllByRole('cell').map(c => c.textContent)).toEqual(['1', '$80', '$120']);
    // A bucket with no figure says so with a dash, never $0.
    const other = within(table).getByRole('rowheader', { name: 'Other' }).closest('tr')!;
    expect(within(other).getAllByRole('cell').map(c => c.textContent)).toEqual(['1', '—', '—']);
  });

  it('keeps the whole method on the page, folded behind a disclosure', async () => {
    renderWithProviders(<ValuationPage />);

    const summary = await screen.findByText('The method in detail');
    const details = summary.closest('details')!;
    expect(details).not.toHaveAttribute('open');
    expect(within(details).getByText(/the listed price is the sale price/i)).toBeInTheDocument();
    expect(within(details).getByText(/measured against 706/i)).toBeInTheDocument();
  });
});
