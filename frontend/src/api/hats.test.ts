import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { listAllHats, listDisposedHats, FULL_COLLECTION_LIMIT } from './hats';
import { hatFixture } from '../test/fixtures';

/**
 * `GET /api/hats` caps `limit` at 1000. Every page that totals, filters or
 * shuffles the collection client-side asks for all of it, so a collection past
 * the cap came back truncated and simply looked smaller and worth less — the
 * server publishes the real size in `X-Total-Count` and logs a warning, and
 * nothing on the client read either.
 */

function page(count: number, total: number, startId: number) {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ 'X-Total-Count': String(total) }),
    json: async () =>
      Array.from({ length: count }, (_, i) => hatFixture({ id: startId + i })),
  };
}

const realFetch = globalThis.fetch;

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { globalThis.fetch = realFetch; });

describe('listAllHats — the whole collection means the whole collection', () => {
  it('follows X-Total-Count past the page cap', async () => {
    const total = FULL_COLLECTION_LIMIT + 234;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(page(FULL_COLLECTION_LIMIT, total, 1))
      .mockResolvedValueOnce(page(234, total, FULL_COLLECTION_LIMIT + 1));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const hats = await listAllHats();

    expect(hats).toHaveLength(total);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    // Second request must actually advance, or this loops on page one.
    const secondUrl = String(fetchMock.mock.calls[1][0]);
    expect(secondUrl).toContain(`offset=${FULL_COLLECTION_LIMIT}`);
  });

  it('stops after one request when the collection fits', async () => {
    const fetchMock = vi.fn().mockResolvedValue(page(3, 3, 1));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    expect(await listAllHats()).toHaveLength(3);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('trusts a single page when the server sends no total', async () => {
    // An older server, or a proxy that strips the header. Looping until the
    // backstop would turn a missing header into 50 requests.
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, headers: new Headers(),
      json: async () => [hatFixture({ id: 1 })],
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    expect(await listAllHats()).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('does not loop forever when the total is larger than the data', async () => {
    // A total that never gets reached — a miscounted header, or rows deleted
    // between pages. An empty page has to end it, or this runs to the backstop
    // on every load.
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(page(2, 99, 1))
      .mockResolvedValue(page(0, 99, 3));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    expect(await listAllHats()).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('keeps disposed hats on their own query', async () => {
    // These two must never merge: a disposed hat is not owned, so it belongs
    // in realized proceeds and nowhere near what the collection is worth.
    const fetchMock = vi.fn().mockResolvedValue(page(1, 1, 1));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await listDisposedHats();

    expect(String(fetchMock.mock.calls[0][0])).toContain('status=disposed');
  });
});
