import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { PurchasesCard } from './PurchasesCard';
import { apiFetch } from '../../api/client';

vi.mock('../../api/client', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    apiFetch: vi.fn()
  };
});

const fetchMock = vi.mocked(apiFetch);

const PREVIEW = {
  would_import: 12, duplicates: 3, unusable: 0, likely_accessories: 2,
  would_match: 9, would_not_match: 3, ambiguous: 1,
  would_match_backlog: 0, would_match_total: 9,
};

/** Route each call by path so order doesn't matter. */
function route(handlers: Record<string, unknown>) {
  fetchMock.mockImplementation((path: string) => {
    for (const [needle, value] of Object.entries(handlers)) {
      if (path.includes(needle)) return Promise.resolve(value) as never;
    }
    return Promise.resolve([]) as never;
  });
}

/** jsdom's File has .text(), which is what the card reads. */
function jsonFile(body: unknown, name = 'melin-purchases.json') {
  return new File([JSON.stringify(body)], name, { type: 'application/json' });
}

/** The figure under a metric tile's label — the tiles are a `<dl>`, so the
 *  value is the `<dd>` that follows the `<dt>`. */
async function metric(label: string): Promise<string> {
  const term = await screen.findByText(label, { selector: 'dt' });
  return term.nextElementSibling?.textContent ?? '';
}

async function pick(file: File) {
  // By label, not by querySelector — the control carries an aria-label because
  // the visible labels in this app have no htmlFor, and a test reaching past
  // that is how a control ships unlabeled.
  await userEvent.upload(screen.getByLabelText('Purchase history JSON file'), file);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('PurchasesCard', () => {
  beforeEach(() => vi.clearAllMocks());

  it('previews a picked file before writing anything', async () => {
    route({ 'dry_run=true': PREVIEW, '/api/admin/purchases': [] });

    renderWithProviders(<PurchasesCard />);
    await pick(jsonFile([{ item_title: 'Trenches Icon Hydro - Camo' }]));

    expect(await screen.findByText('12')).toBeInTheDocument();
    expect(screen.getByText('melin-purchases.json')).toBeInTheDocument();

    // The whole point of the preview: nothing is imported until confirmed.
    expect(fetchMock).not.toHaveBeenCalledWith(
      '/api/admin/purchases/import',
      expect.anything(),
    );
  });

  it('imports only after the confirm button', async () => {
    route({
      'dry_run=true': PREVIEW,
      '/api/admin/purchases/import': { imported: 12, skipped: 3, matched: 9, unmatched: 3 },
      '/api/admin/purchases': [],
    });

    renderWithProviders(<PurchasesCard />);
    await pick(jsonFile([{ item_title: 'Trenches Icon Hydro - Camo' }]));

    const confirm = await screen.findByRole('button', { name: /Import 12 and match/ });
    await userEvent.click(confirm);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/admin/purchases/import',
        expect.objectContaining({ method: 'POST' }),
      ),
    );
    // The outcome is a toast now (the tiles are the lasting record), so it
    // reads in sentence case — the same counts, the same words.
    expect(await screen.findByText(/imported 12, matched 9 to hats/i)).toBeInTheDocument();
  });

  it('sends the file contents, unwrapping an {items: [...]} envelope', async () => {
    route({ 'dry_run=true': PREVIEW, '/api/admin/purchases': [] });

    renderWithProviders(<PurchasesCard />);
    await pick(jsonFile({ items: [{ item_title: 'A-Game Hydro' }] }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([p]) => String(p).includes('dry_run=true'));
      expect(call).toBeDefined();
      expect(JSON.parse(String(call![1]!.body))).toEqual({
        items: [{ item_title: 'A-Game Hydro' }],
      });
    });
  });

  it('says so when every line is already on record', async () => {
    route({
      'dry_run=true': { ...PREVIEW, would_import: 0, duplicates: 294 },
      '/api/admin/purchases': [],
    });

    renderWithProviders(<PurchasesCard />);
    await pick(jsonFile([{ item_title: 'Trenches Icon Hydro - Camo' }]));

    expect(await screen.findByText(/all 294 lines are already on record/)).toBeInTheDocument();
    // Nothing to do, so no confirm button to press.
    expect(screen.queryByRole('button', { name: /^Import \d+ and match/ })).toBeNull();
  });

  it('reports a file that is not a list of line items rather than posting it', async () => {
    route({ '/api/admin/purchases': [] });

    renderWithProviders(<PurchasesCard />);
    await pick(jsonFile({ orders: 'nope' }));

    expect(await screen.findByText(/Expected a JSON array/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('dry_run=true'),
      expect.anything(),
    );
  });

  it('warns that importing also matches purchases already on record', async () => {
    // The shipped bug: previewing one new line reported "0 would match" while
    // the import matched 144 and wrote 144 hat prices. The blast radius has to
    // be on screen before the button is pressed.
    route({
      'dry_run=true': {
        ...PREVIEW, would_import: 1, would_match: 0,
        would_match_backlog: 144, would_match_total: 144,
      },
      '/api/admin/purchases': [],
    });

    renderWithProviders(<PurchasesCard />);
    await pick(jsonFile([{ item_title: 'Coach Hydro - Black' }]));

    expect(
      await screen.findByText(/Also matches 144 purchases already on record/),
    ).toBeInTheDocument();
    expect(screen.getByText(/writes a colorway and cost basis onto 144 hats/)).toBeInTheDocument();
  });

  it('stays quiet about the backlog when there is none', async () => {
    route({ 'dry_run=true': PREVIEW, '/api/admin/purchases': [] });

    renderWithProviders(<PurchasesCard />);
    await pick(jsonFile([{ item_title: 'Coach Hydro - Black' }]));

    await screen.findByText('12');
    expect(screen.queryByText(/already on record\./)).toBeNull();
  });

  it('offers Unlink all only once something is linked', async () => {
    route({
      '/api/admin/purchases': [
        { id: 1, order_ref: 'A', order_date: null, item_title: 'Hydro', price: 79, hat_id: null },
      ],
    });

    const { unmount } = renderWithProviders(<PurchasesCard />);
    // The counts used to be one "1 purchases · 0 linked" line; they are tiles.
    expect(await metric('Purchases')).toBe('1');
    expect(await metric('Linked to hats')).toBe('0');
    expect(screen.queryByRole('button', { name: 'Unlink all' })).toBeNull();
    unmount();

    route({
      '/api/admin/purchases': [
        { id: 1, order_ref: 'A', order_date: null, item_title: 'Hydro', price: 79, hat_id: 7 },
      ],
    });
    renderWithProviders(<PurchasesCard />);
    expect(await screen.findByRole('button', { name: 'Unlink all' })).toBeInTheDocument();
  });

  it('offers a copyable prompt for building the JSON from email', async () => {
    // The data lives in the user's inbox and the card previously assumed they
    // already had a JSON file, which nothing in the app produces.
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    // jsdom exposes navigator.clipboard as a getter-only property — and does
    // not claim a secure context, which `lib/clipboard.copyText` requires
    // before it will touch the async clipboard (over plain HTTP it falls back
    // to selection). Claim one here so this test exercises the async path.
    vi.stubGlobal('isSecureContext', true);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText }, configurable: true,
    });
    route({ '/api/admin/purchases': [] });

    renderWithProviders(<PurchasesCard />);

    await user.click(await screen.findByText(/get one from your email/i));
    await user.click(screen.getByRole('button', { name: 'Copy the import prompt' }));

    expect(writeText).toHaveBeenCalledTimes(1);
    const copied = writeText.mock.calls[0][0] as string;
    // The field names are the point — a prompt that copies prose the importer
    // cannot read is worse than no prompt, because the import then "succeeds".
    expect(copied).toContain('item_title');
    expect(copied).toContain('order_date');
    expect(copied).not.toContain('purchased_at');
    expect(await screen.findByRole('button', { name: 'Copied the import prompt' })).toBeInTheDocument();
  });

  it('survives a clipboard the browser refuses', async () => {
    // navigator.clipboard is permission-gated and absent over plain http, which
    // is exactly how this app is served on a LAN without the TLS overlay. The
    // prompt is on screen and selectable either way.
    const user = userEvent.setup();
    vi.stubGlobal('isSecureContext', true);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
      configurable: true,
    });
    route({ '/api/admin/purchases': [] });

    renderWithProviders(<PurchasesCard />);
    await user.click(await screen.findByText(/get one from your email/i));
    await user.click(screen.getByRole('button', { name: 'Copy the import prompt' }));

    // No crash, no false "Copied".
    expect(await screen.findByRole('button', { name: 'Copy the import prompt' })).toBeInTheDocument();
    expect(await screen.findByText(/Couldn.t copy the import prompt/)).toBeInTheDocument();
  });
});

const HAT_7 = {
  id: 7, display_id: 'A-001-01', model_name: 'Trenches Hydro', artist_series: 'Have More Fun',
  colorway: null, photo_path: null, thumb_path: null,
};
const BASE = { link_confirmed_at: null, suspect: false, accessory: false, hat: null };
const LINKED = [
  { ...BASE, id: 1, order_ref: 'A', order_date: null, item_title: 'Trenches Hydro', price: 79, hat_id: 7, hat: HAT_7 },
  { ...BASE, id: 2, order_ref: 'B', order_date: null, item_title: 'Travel case', price: 40, hat_id: null, accessory: true },
];
const UNLINKED_HAT = {
  ...BASE, id: 3, order_ref: 'C', order_date: null, item_title: 'Odysea Hydro - Navy', price: 79, hat_id: null,
  colorway: 'Navy',
};
const SUSPECT = {
  ...BASE, id: 4, order_ref: 'D', order_date: null, item_title: 'Odysea 23XI Hydro - White Speed Camo',
  price: 89, hat_id: 7, hat: HAT_7, suspect: true,
};

/** Open one of the list's tabs, by its visible name. */
async function openTab(user: ReturnType<typeof userEvent.setup>, name: RegExp) {
  await user.click(await screen.findByRole('button', { name }));
}

describe('PurchasesCard — status and loading', () => {
  beforeEach(() => vi.clearAllMocks());

  it('names the state in the header: none, waiting, to check, all linked', async () => {
    route({ '/api/admin/purchases': [] });
    const first = renderWithProviders(<PurchasesCard />);
    expect(await screen.findByText('None imported')).toBeInTheDocument();
    first.unmount();

    // A travel case is an accessory, not a hat waiting for one: on the
    // owner's history 78 of 95 "unmatched" lines were cases, burying the 17
    // hat purchases actually waiting.
    route({ '/api/admin/purchases': LINKED });
    const second = renderWithProviders(<PurchasesCard />);
    expect(await screen.findByText('All linked')).toBeInTheDocument();
    second.unmount();

    route({ '/api/admin/purchases': [...LINKED, UNLINKED_HAT] });
    const third = renderWithProviders(<PurchasesCard />);
    expect(await screen.findByText('1 need a hat')).toBeInTheDocument();
    third.unmount();

    route({ '/api/admin/purchases': [...LINKED, SUSPECT] });
    renderWithProviders(<PurchasesCard />);
    expect(await screen.findByText('1 to check')).toBeInTheDocument();
  });

  it('does not flash "0 purchases" while the list is loading', async () => {
    // The old one-line summary rendered from `data ?? []`, so every visit
    // opened on "0 purchases · 0 linked" — a claim, not a placeholder.
    fetchMock.mockImplementation(() => new Promise(() => {}) as never);
    renderWithProviders(<PurchasesCard />);
    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(screen.queryByText('Purchases', { selector: 'dt' })).toBeNull();
    expect(screen.queryByText('None imported')).toBeNull();
  });
});

describe('PurchasesCard — Unlink all asks first', () => {
  beforeEach(() => vi.clearAllMocks());

  const unlinkAllCalled = () =>
    fetchMock.mock.calls.some(([p]) => String(p).includes('/unmatch-all'));

  it('does nothing when the dialog is canceled', async () => {
    const user = userEvent.setup();
    route({ '/api/admin/purchases': LINKED });
    renderWithProviders(<PurchasesCard />);

    await user.click(await screen.findByRole('button', { name: 'Unlink all' }));
    const dialog = await screen.findByRole('alertdialog');
    // The consequences are stated before anything happens.
    expect(dialog).toHaveTextContent(/colorway, cost basis and purchase date/);
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(unlinkAllCalled()).toBe(false);
  });

  it('unlinks only once the dialog is confirmed, then says what it did', async () => {
    const user = userEvent.setup();
    route({
      '/unmatch-all': { unmatched: 1, fields_cleared: 2 },
      '/api/admin/purchases': LINKED,
    });
    renderWithProviders(<PurchasesCard />);

    await user.click(await screen.findByRole('button', { name: 'Unlink all' }));
    expect(unlinkAllCalled()).toBe(false);

    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Unlink all' }));

    await waitFor(() => expect(unlinkAllCalled()).toBe(true));
    expect(await screen.findByText(/Unlinked 1, cleared 2 fields/)).toBeInTheDocument();
  });
});

describe('PurchasesCard — single unlink is optimistic', () => {
  beforeEach(() => vi.clearAllMocks());

  it('drops the link the moment it is pressed, before the server answers', async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation((path: string) => {
      // The unlink never answers: whatever the card shows now, it shows
      // without the server's help.
      if (path.includes('/unmatch')) return new Promise(() => {}) as never;
      return Promise.resolve(LINKED) as never;
    });
    renderWithProviders(<PurchasesCard />);

    await openTab(user, /^Linked/);
    await user.click(await screen.findByRole('button', { name: 'Unlink Trenches Hydro from its hat' }));

    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Unlink Trenches Hydro from its hat' })).toBeNull(),
    );
    expect(await metric('Linked to hats')).toBe('0');
  });

  it('puts the link back when the server refuses, and says why', async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation((path: string) => {
      if (path.includes('/unmatch')) return Promise.reject(new Error('Purchase not found')) as never;
      return Promise.resolve(LINKED) as never;
    });
    renderWithProviders(<PurchasesCard />);

    await openTab(user, /^Linked/);
    await user.click(await screen.findByRole('button', { name: 'Unlink Trenches Hydro from its hat' }));

    expect(await screen.findByText(/Purchase not found/)).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Unlink Trenches Hydro from its hat' }))
      .toBeInTheDocument();
    expect(await metric('Linked to hats')).toBe('1');
  });
});

/** Every request the card made whose path contains `needle`. */
const callsTo = (needle: string) =>
  fetchMock.mock.calls.filter(([p]) => String(p).includes(needle));

describe('PurchasesCard — checking the links earlier matching made', () => {
  beforeEach(() => vi.clearAllMocks());

  it('opens on the links to check, each beside the hat it is on', async () => {
    route({ '/api/admin/purchases': [...LINKED, SUSPECT] });
    renderWithProviders(<PurchasesCard />);
    expect(await screen.findByText('Odysea 23XI Hydro - White Speed Camo')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'A-001-01' })).toHaveAttribute('href', '/hats/7');
    expect(screen.getByText(/series “Have More Fun”/)).toBeInTheDocument();
  });

  it('keeps a link you vouch for', async () => {
    const user = userEvent.setup();
    route({ '/api/admin/purchases': [...LINKED, SUSPECT] });
    renderWithProviders(<PurchasesCard />);
    await user.click(await screen.findByRole('button', { name: /^Keep Odysea 23XI/ }));
    await waitFor(() => expect(callsTo('/purchases/4/confirm')).toHaveLength(1));
  });

  it('unlinking one clears what it copied onto the hat', async () => {
    const user = userEvent.setup();
    route({ '/api/admin/purchases': [...LINKED, SUSPECT] });
    renderWithProviders(<PurchasesCard />);
    await user.click(await screen.findByRole('button', { name: /^Unlink Odysea 23XI .* clear what it copied/ }));
    await waitFor(() => expect(callsTo('/purchases/4/unmatch?clear_copied=true')).toHaveLength(1));
  });

  it('unlinking all of them asks first, then sends one request', async () => {
    const user = userEvent.setup();
    route({ '/api/admin/purchases': [...LINKED, SUSPECT] });
    renderWithProviders(<PurchasesCard />);
    await user.click(await screen.findByRole('button', { name: 'Unlink all 1' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent(/Links you made or kept are not touched/);
    expect(callsTo('/unlink-suspect')).toHaveLength(0);
    await user.click(within(dialog).getByRole('button', { name: 'Unlink all' }));
    await waitFor(() => expect(callsTo('/unlink-suspect')).toHaveLength(1));
  });
});

const OPTIONS = {
  purchase: UNLINKED_HAT,
  options: [
    { hat_id: 9, display_id: 'A-002-03', model_name: 'Odysea Hydro', artist_series: null,
      colorway: 'Bone', size: 'classic', construction: 'HYDRO', photo_path: null, thumb_path: null,
      purchase_price: null, linked_purchase_id: null, fits: true, score: 14, agrees: ['model', 'size'] },
    { hat_id: 7, display_id: 'A-001-01', model_name: 'Trenches Hydro', artist_series: 'Have More Fun',
      colorway: null, size: 'classic', construction: 'HYDRO', photo_path: null, thumb_path: null,
      purchase_price: 79, linked_purchase_id: 1, fits: false, score: 2, agrees: [] },
  ],
};

describe('PurchasesCard — linking a purchase to the hat you choose', () => {
  beforeEach(() => vi.clearAllMocks());

  async function openPicker(user: ReturnType<typeof userEvent.setup>) {
    route({
      '/purchases/3/hats': OPTIONS,
      '/purchases/3/link': { hat_id: 9, wrote: [], moved_from_hat_id: null, replaced_purchase_id: null },
      '/api/admin/purchases': [...LINKED, UNLINKED_HAT],
    });
    renderWithProviders(<PurchasesCard />);
    await user.click(await screen.findByRole('button', { name: 'Link to hat…' }));
    return screen.findByRole('dialog', { name: 'Which hat is this?' });
  }

  it('offers every hat, best fit first, and says which one already has a purchase', async () => {
    const user = userEvent.setup();
    const dialog = await openPicker(user);
    const rows = await within(dialog).findAllByRole('button', { name: /A-00/ });
    expect(rows[0]).toHaveTextContent('A-002-03');
    expect(rows[0]).toHaveTextContent('Fits');
    expect(rows[1]).toHaveTextContent(/Has another purchase/);
  });

  it('links to the chosen hat, and asks before using the receipt’s colorway over the hat’s', async () => {
    const user = userEvent.setup();
    const dialog = await openPicker(user);
    await user.click(await within(dialog).findByRole('button', { name: /A-002-03/ }));
    const colorway = within(dialog).getByRole('checkbox', {
      name: /receipt’s colorway “Navy” instead of the hat’s “Bone”/,
    });
    expect(colorway).not.toBeChecked();
    await user.click(colorway);
    await user.click(within(dialog).getByRole('button', { name: 'Link to A-002-03' }));

    await waitFor(() => expect(callsTo('/purchases/3/link')).toHaveLength(1));
    const [, init] = callsTo('/purchases/3/link')[0];
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      hat_id: 9, replace: false, receipt_colorway: true,
    });
  });

  it('choosing a hat that already has a purchase says so, and replaces it', async () => {
    const user = userEvent.setup();
    const dialog = await openPicker(user);
    await user.click(await within(dialog).findByRole('button', { name: /A-001-01/ }));
    expect(dialog).toHaveTextContent(/already has a purchase linked\. Linking replaces it/);
    await user.click(within(dialog).getByRole('button', { name: 'Link to A-001-01' }));
    await waitFor(() => expect(callsTo('/purchases/3/link')).toHaveLength(1));
    const [, init] = callsTo('/purchases/3/link')[0];
    expect(JSON.parse(String((init as RequestInit).body)).replace).toBe(true);
  });
});
