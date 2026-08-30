import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { SharedPricesCard } from './SharedPricesCard';
import * as api from '../../api/settings';
import * as purchaseApi from '../../api/purchases';
import type {
  SharedPriceGroup, SharedPriceHat, UnclaimedFromPurchases,
} from '../../types';

vi.mock('../../api/settings', () => ({
  auditSharedPrices: vi.fn(),
  getUnclaimedFromPurchases: vi.fn(),
}));
vi.mock('../../api/purchases', () => ({
  rematchPurchases: vi.fn(),
}));

const mocked = vi.mocked(api);
const purchases = vi.mocked(purchaseApi);

function unclaimed(over: Partial<UnclaimedFromPurchases> = {}): UnclaimedFromPurchases {
  return { colorways: 0, prices: 0, ambiguous: 0, ...over };
}

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

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getUnclaimedFromPurchases.mockResolvedValue(unclaimed());
});

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
    // colorway catalog and the analysis pending count both fell into.
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

  it('offers to fill the colorways sitting unclaimed in the order history', async () => {
    // The card used to say a colorway was the one thing only the owner could
    // supply. On the real collection that was false for 17 of 82 hats: the
    // answers were in already-imported purchases that matching had never been
    // re-run over, because matching runs at the end of an import and nowhere
    // else.
    mocked.auditSharedPrices.mockResolvedValue([group()]);
    mocked.getUnclaimedFromPurchases.mockResolvedValue(
      unclaimed({ colorways: 17, prices: 16, ambiguous: 4 }),
    );

    renderWithProviders(<SharedPricesCard />);

    const button = await screen.findByRole('button', {
      name: /Fill 17 from purchase history/,
    });
    expect(screen.getByText(/17 colorways can be filled/)).toBeInTheDocument();
    // Applying does more than colorways, and the count of coin-toss matches is
    // stated rather than hidden.
    expect(screen.getByText(/sets 16 purchase prices/)).toBeInTheDocument();
    expect(screen.getByText(/4 of them were a tie/)).toBeInTheDocument();

    await userEvent.click(button);
    expect(purchases.rematchPurchases).toHaveBeenCalled();
  });

  it('offers nothing when the backlog is empty', async () => {
    // A standing button that does nothing trains you to ignore it.
    mocked.auditSharedPrices.mockResolvedValue([group()]);
    mocked.getUnclaimedFromPurchases.mockResolvedValue(unclaimed());

    renderWithProviders(<SharedPricesCard />);
    await screen.findByText(/Prices shared by many hats/);
    expect(screen.queryByRole('button', { name: /purchase history/ }))
      .not.toBeInTheDocument();
  });

  it('offers the backlog even when no price is shared yet', async () => {
    // The offer lives outside the "there are groups" branch: acting early is
    // what stops these hats landing on a line median in the first place.
    mocked.auditSharedPrices.mockResolvedValue([]);
    mocked.getUnclaimedFromPurchases.mockResolvedValue(unclaimed({ colorways: 3 }));

    renderWithProviders(<SharedPricesCard />);
    expect(await screen.findByRole('button', { name: /Fill 3 from purchase history/ }))
      .toBeInTheDocument();
  });
});
