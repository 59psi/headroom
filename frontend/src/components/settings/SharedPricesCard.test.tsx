import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import { SharedPricesCard } from './SharedPricesCard';
import * as api from '../../api/settings';
import type { SharedPriceGroup, SharedPriceHat } from '../../types';

vi.mock('../../api/settings', () => ({
  auditSharedPrices: vi.fn(),
}));

const mocked = vi.mocked(api);

function hat(over: Partial<SharedPriceHat> = {}): SharedPriceHat {
  return { hat_id: 1, display_id: null, has_colorway: false, ...over };
}

function group(over: Partial<SharedPriceGroup> = {}): SharedPriceGroup {
  return {
    resale_price: 85,
    source: 'Melin Recap · median of 13 live Trenches Hydro listings',
    hat_count: 1,
    hats: [hat()],
    missing_colorway: 1,
    ...over,
  };
}

beforeEach(() => { vi.clearAllMocks(); });

describe('SharedPricesCard', () => {
  it('draws each hat its OWN label, so a caseless one cannot shift the rest', async () => {
    // The bug this pins: ids and labels were two parallel arrays, and a hat
    // with no case contributed an id but no label — so every later label slid
    // onto the wrong hat's link, pointing at hat A under hat B's shelf id.
    // It was invisible in tests because every fixture hat was caseless, which
    // left the label array empty and the two trivially "aligned".
    mocked.auditSharedPrices.mockResolvedValue([group({
      hat_count: 3,
      missing_colorway: 0,
      hats: [
        hat({ hat_id: 11, display_id: null, has_colorway: true }),
        hat({ hat_id: 12, display_id: 'A-001-01', has_colorway: true }),
        hat({ hat_id: 13, display_id: 'A-001-02', has_colorway: true }),
      ],
    })]);

    renderWithProviders(<SharedPricesCard />);

    // The cased hats wear their own shelf ids...
    expect(await screen.findByRole('link', { name: 'A-001-01' }))
      .toHaveAttribute('href', '/hats/12');
    expect(screen.getByRole('link', { name: 'A-001-02' }))
      .toHaveAttribute('href', '/hats/13');
    // ...and the caseless one falls back to its id rather than borrowing a label.
    expect(screen.getByRole('link', { name: '#11' }))
      .toHaveAttribute('href', '/hats/11');
  });

  it('sends a hat with no colorway to the form where a colorway is entered', async () => {
    // The actionable half has to be actionable. A count alone, next to links
    // that land on a read-only page, names the fix without offering it.
    mocked.auditSharedPrices.mockResolvedValue([group({
      hat_count: 2,
      missing_colorway: 1,
      hats: [
        hat({ hat_id: 21, display_id: 'A-001-01', has_colorway: false }),
        hat({ hat_id: 22, display_id: 'A-001-02', has_colorway: true }),
      ],
    })]);

    renderWithProviders(<SharedPricesCard />);

    expect(await screen.findByRole('link', { name: /A-001-01/ }))
      .toHaveAttribute('href', '/hats/21/edit');
    expect(screen.getByRole('link', { name: 'A-001-02' }))
      .toHaveAttribute('href', '/hats/22');
  });

  it('states how many hats it did not name, rather than truncating silently', async () => {
    // A truncated list reads exactly like a short one — the same trap the
    // colorway catalogue and the analysis pending count both fell into.
    mocked.auditSharedPrices.mockResolvedValue([group({
      hat_count: 30,
      missing_colorway: 30,
      hats: Array.from({ length: 30 }, (_, i) => hat({ hat_id: 100 + i })),
    })]);

    renderWithProviders(<SharedPricesCard />);

    expect(await screen.findByText(/and 22 more/)).toBeInTheDocument();
  });

  it('says nothing is shared rather than rendering an empty list', async () => {
    mocked.auditSharedPrices.mockResolvedValue([]);
    renderWithProviders(<SharedPricesCard />);
    expect(await screen.findByText(/every price is describing its own hat/))
      .toBeInTheDocument();
  });
});
