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
import { caCertificateAvailable } from './settings';

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
