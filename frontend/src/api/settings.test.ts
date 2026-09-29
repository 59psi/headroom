/**
 * `caCertificateAvailable` against what the endpoint really returns.
 *
 * The Trust-this-device card probed `/api/public/ca-certificate` through
 * `apiFetch`, which parses every 200 as JSON. The endpoint answers a PEM file,
 * so `.json()` rejected, the probe returned false, and the card never rendered
 * on the LAN-HTTPS overlay — the only deployment it exists for — from its
 * first commit. The card's own test mocked `apiFetch` resolving a string, a
 * value `apiFetch` cannot produce for that route, so it could not see this.
 * This test hands the probe a real `Response` carrying a PEM body.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  caCertificateAvailable, getModelOptions, inventoryReportUrl, releaseFrozenPrices, retryFailedAnalysis,
} from './settings';

const PEM = '-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----\n';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('caCertificateAvailable', () => {
  it('is true for a 200 whose body is a PEM, not JSON', async () => {
    const resp = new Response(PEM, {
      status: 200,
      headers: { 'Content-Type': 'application/x-x509-ca-cert' },
    });
    // Sanity: this body is exactly what broke the old probe.
    await expect(resp.clone().json()).rejects.toBeInstanceOf(SyntaxError);
    vi.stubGlobal('fetch', vi.fn(async () => resp));

    expect(await caCertificateAvailable()).toBe(true);
  });

  it('is false when the overlay is not running (404)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"no"}', { status: 404 })));

    expect(await caCertificateAvailable()).toBe(false);
  });

  it('is false when the request itself fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('network down'); }));

    expect(await caCertificateAvailable()).toBe(false);
  });
});

/** Stub fetch with a JSON 200 and hand back the URLs it was called with. */
function urls(body: unknown = {}) {
  const fetchMock = vi.fn(async () => new Response(
    JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } },
  ));
  vi.stubGlobal('fetch', fetchMock);
  return () => fetchMock.mock.calls.map(c => new URL(String((c as unknown[])[0]), 'http://x'));
}

describe('releaseFrozenPrices — an empty selection is not "all"', () => {
  it('sends nothing for an empty list, because absent hat_ids means EVERY frozen hat', async () => {
    const sent = urls();
    const result = await releaseFrozenPrices([], false);
    expect(sent()).toHaveLength(0);
    expect(result).toEqual({ dry_run: false, released: 0, hats: [] });
  });

  it('names each chosen hat in the query string', async () => {
    const sent = urls({ dry_run: false, released: 2, hats: [] });
    await releaseFrozenPrices([3, 9], false);
    const [u] = sent();
    expect(u.pathname).toBe('/api/admin/prices/release');
    expect(u.searchParams.getAll('hat_ids')).toEqual(['3', '9']);
    expect(u.searchParams.get('dry_run')).toBe('false');
  });

  it('leaves hat_ids off only for the explicit null (every frozen hat)', async () => {
    const sent = urls({ dry_run: true, released: 0, hats: [] });
    await releaseFrozenPrices(null, true);
    expect(sent()[0].searchParams.has('hat_ids')).toBe(false);
  });
});

describe('inventoryReportUrl', () => {
  it('asks for a photo-less report only when photos are turned off', () => {
    expect(inventoryReportUrl()).toBe('/api/admin/inventory-report');
    expect(inventoryReportUrl({ includePhotos: false })).toBe(
      '/api/admin/inventory-report?include_photos=false',
    );
    expect(inventoryReportUrl({ includeDisposed: true, includePhotos: true })).toBe(
      '/api/admin/inventory-report?include_disposed=true',
    );
  });
});

describe('retryFailedAnalysis', () => {
  it('encodes the failure reason — reasons are raw error text with spaces, & and ?', async () => {
    const sent = urls({ queued: 0, worker_alive: true, job: null });
    const reason = "Claude said: overloaded & retry? {'type': 'error'}";
    await retryFailedAnalysis(reason);
    expect(sent()[0].searchParams.get('reason')).toBe(reason);
    expect(sent()[0].searchParams.getAll('reason')).toHaveLength(1);
  });

  it('sends no reason for "retry everything that failed"', async () => {
    const sent = urls({ queued: 0, worker_alive: true, job: null });
    await retryFailedAnalysis();
    expect(sent()[0].search).toBe('');
  });
});

describe('getModelOptions', () => {
  // The server keeps Anthropic's listing for hours; `?refresh=1` makes it
  // ask again. The card's ordinary fetch must never send it — every Settings
  // visit would otherwise be a round trip to Anthropic — and Refresh must.
  it('reads the cached list by default', async () => {
    const sent = urls({ models: [] });
    await getModelOptions();
    expect(sent()[0].pathname).toBe('/api/settings/models');
    expect(sent()[0].search).toBe('');
  });

  it('asks for a fresh check with Anthropic on request', async () => {
    const sent = urls({ models: [] });
    await getModelOptions(true);
    expect(sent()[0].pathname).toBe('/api/settings/models');
    expect(sent()[0].searchParams.get('refresh')).toBe('1');
  });

  it("does not read TanStack's query context as a request to refresh", async () => {
    // What it receives if ever passed to `useQuery` as a bare `queryFn` —
    // which tsc accepts. An object is truthy; it is not `true`.
    const sent = urls({ models: [] });
    const context = { queryKey: ['settings', 'models'], signal: new AbortController().signal };
    await (getModelOptions as (ctx: unknown) => Promise<unknown>)(context);
    expect(sent()[0].search).toBe('');
  });
});
