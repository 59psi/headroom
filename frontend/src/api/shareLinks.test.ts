/**
 * The request `createShareLink` actually sends.
 *
 * A share link is the whole collection — every hat, its photo, its room — and
 * it once went out permanent every time: the helper sent `expires_days: null`
 * unconditionally, which the server reads as "never expires", so its 30-day
 * default could never apply. The card's tests mock this function, so nothing
 * looked at the body; these do.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createShareLink } from './shareLinks';

afterEach(() => {
  vi.unstubAllGlobals();
});

function capture() {
  const fetchMock = vi.fn(async () => new Response(
    JSON.stringify({ id: 1, token: 't', url_path: '/share/t' }),
    { status: 201, headers: { 'Content-Type': 'application/json' } },
  ));
  vi.stubGlobal('fetch', fetchMock);
  return () => {
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    return JSON.parse(String(init.body)) as Record<string, unknown>;
  };
}

describe('createShareLink', () => {
  it('leaves expires_days OUT when no expiry was chosen, so the server default applies', async () => {
    const body = capture();
    await createShareLink('Family');
    expect(body()).toEqual({ label: 'Family' });
    expect('expires_days' in body()).toBe(false);
  });

  it('sends null only when "never expires" was asked for', async () => {
    const body = capture();
    await createShareLink('Insurer', null);
    expect(body()).toEqual({ label: 'Insurer', expires_days: null });
  });

  it('sends a chosen number of days as it is', async () => {
    const body = capture();
    await createShareLink('Friend', 7);
    expect(body()).toEqual({ label: 'Friend', expires_days: 7 });
  });
});
