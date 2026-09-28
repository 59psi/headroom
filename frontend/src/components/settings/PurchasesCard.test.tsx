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
    await user.click(screen.getByRole('button', { name: 'Copy prompt' }));

    expect(writeText).toHaveBeenCalledTimes(1);
    const copied = writeText.mock.calls[0][0] as string;
    // The field names are the point — a prompt that copies prose the importer
    // cannot read is worse than no prompt, because the import then "succeeds".
    expect(copied).toContain('item_title');
    expect(copied).toContain('order_date');
    expect(copied).not.toContain('purchased_at');
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
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
    await user.click(screen.getByRole('button', { name: 'Copy prompt' }));

    // No crash, no false "Copied".
    expect(await screen.findByRole('button', { name: 'Copy prompt' })).toBeInTheDocument();
  });
});

const LINKED = [
  { id: 1, order_ref: 'A', order_date: null, item_title: 'Trenches Hydro', price: 79, hat_id: 7 },
  { id: 2, order_ref: 'B', order_date: null, item_title: 'Travel case', price: 40, hat_id: null },
];

describe('PurchasesCard — status and loading', () => {
  beforeEach(() => vi.clearAllMocks());

  it('names the state in the header: none, some unlinked, all linked', async () => {
    route({ '/api/admin/purchases': [] });
    const first = renderWithProviders(<PurchasesCard />);
    expect(await screen.findByText('None imported')).toBeInTheDocument();
    first.unmount();

    route({ '/api/admin/purchases': LINKED });
    const second = renderWithProviders(<PurchasesCard />);
    // The travel case never links — "1 unlinked", not a claim that all are.
    expect(await screen.findByText('1 unlinked')).toBeInTheDocument();
    second.unmount();

    route({ '/api/admin/purchases': [LINKED[0]] });
    renderWithProviders(<PurchasesCard />);
    expect(await screen.findByText('All linked')).toBeInTheDocument();
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

    await user.click(await screen.findByRole('button', { name: 'Unlink Trenches Hydro from its hat' }));

    expect(await screen.findByText(/Purchase not found/)).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Unlink Trenches Hydro from its hat' }))
      .toBeInTheDocument();
    expect(await metric('Linked to hats')).toBe('1');
  });
});
