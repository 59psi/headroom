/**
 * The hat page's Purchase panel: which order the hat came from, and the
 * place to choose it when the matcher could not — from the hat's side.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { hatFixture } from '../../test/fixtures';
import { apiFetch } from '../../api/client';
import { HatPurchasePanel } from './HatPurchasePanel';
import type { PurchaseRead } from '../../types';

vi.mock('../../api/client', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), apiFetch: vi.fn() };
});

const fetchMock = vi.mocked(apiFetch);

function route(handlers: Record<string, unknown>) {
  fetchMock.mockImplementation((path: string) => {
    for (const [needle, value] of Object.entries(handlers)) {
      if (path.includes(needle)) return Promise.resolve(value) as never;
    }
    return Promise.resolve([]) as never;
  });
}

const callsTo = (needle: string) => fetchMock.mock.calls.filter(([p]) => String(p).includes(needle));

const BASE = {
  link_confirmed_at: null, suspect: false, accessory: false, hat: null,
  model_name: null, size: 'classic', quantity: 1, source: 'email',
};
const RECEIPT: PurchaseRead = {
  ...BASE, id: 21, order_ref: '2124958', order_date: '2026-09-09T00:00:00Z',
  item_title: 'Trenches Icon Hydro - Misty Trails', colorway: 'Misty Trails', price: 89, hat_id: null,
};
const ELSEWHERE: PurchaseRead = {
  ...BASE, id: 22, order_ref: '2117554', order_date: '2026-09-03T00:00:00Z',
  item_title: 'Trenches Icon Hydro - Watercolor Camo', colorway: 'Watercolor Camo', price: 89, hat_id: 30,
};
const OPTION = (p: PurchaseRead, extra: object = {}) => ({
  ...p, linked_hat_id: p.hat_id, linked_hat_display_id: p.hat_id ? 'D-023-03' : null,
  fits: true, score: 22, agrees: ['model', 'series', 'size'], ...extra,
});

describe('HatPurchasePanel', () => {
  beforeEach(() => vi.clearAllMocks());

  it('with nothing linked, says how many purchases on record fit', async () => {
    route({ '/purchases/for-hat/5': { linked: [], options: [OPTION(RECEIPT)] } });
    renderWithProviders(<HatPurchasePanel hat={hatFixture({ id: 5 })} />);
    expect(await screen.findByText(/No purchase linked/)).toHaveTextContent('one on record fits');
    expect(screen.getByRole('button', { name: 'Link a purchase…' })).toBeInTheDocument();
  });

  it('shows the linked purchase, and unlinks it', async () => {
    const user = userEvent.setup();
    route({ '/purchases/for-hat/5': { linked: [{ ...RECEIPT, hat_id: 5 }], options: [] } });
    renderWithProviders(<HatPurchasePanel hat={hatFixture({ id: 5 })} />);
    expect(await screen.findByText('Trenches Icon Hydro - Misty Trails')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^Unlink Trenches Icon Hydro - Misty Trails/ }));
    await waitFor(() => expect(callsTo('/purchases/21/unmatch')).toHaveLength(1));
  });

  it('links the purchase you pick to this hat', async () => {
    const user = userEvent.setup();
    route({
      '/purchases/for-hat/5': { linked: [], options: [OPTION(RECEIPT)] },
      '/purchases/21/link': { hat_id: 5, wrote: ['colorway'], moved_from_hat_id: null, replaced_purchase_id: null },
    });
    renderWithProviders(<HatPurchasePanel hat={hatFixture({ id: 5, colorway: null })} />);
    await user.click(await screen.findByRole('button', { name: 'Link a purchase…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Which purchase was this hat?' });
    await user.click(await within(dialog).findByRole('button', { name: /Misty Trails/ }));
    // The hat has no colorway, so there is nothing to choose between.
    expect(within(dialog).queryByRole('checkbox')).toBeNull();
    await user.click(within(dialog).getByRole('button', { name: 'Link this purchase' }));

    await waitFor(() => expect(callsTo('/purchases/21/link')).toHaveLength(1));
    const [, init] = callsTo('/purchases/21/link')[0];
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      hat_id: 5, replace: false, receipt_colorway: false,
    });
  });

  it('a purchase on another hat is offered, and choosing it says it moves', async () => {
    const user = userEvent.setup();
    route({ '/purchases/for-hat/5': { linked: [], options: [OPTION(ELSEWHERE)] } });
    renderWithProviders(<HatPurchasePanel hat={hatFixture({ id: 5 })} />);
    await user.click(await screen.findByRole('button', { name: 'Link a purchase…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Which purchase was this hat?' });
    const row = await within(dialog).findByRole('button', { name: /Watercolor Camo/ });
    expect(row).toHaveTextContent(/On D-023-03 now/);
    await user.click(row);
    expect(dialog).toHaveTextContent(/Moves it off D-023-03/);
  });
});
