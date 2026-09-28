/**
 * The query strings the search helpers build — the parameters the server
 * reads, and the ones left off so a shared URL stays readable.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { searchHats, searchHatsByColor } from './search';
import { getGuestCollection } from './guest';

afterEach(() => {
  vi.unstubAllGlobals();
});

function sent() {
  const fetchMock = vi.fn(async () => new Response(
    JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json' } },
  ));
  vi.stubGlobal('fetch', fetchMock);
  return () => new URL(String((fetchMock.mock.calls[0] as unknown[])[0]), 'http://x');
}

describe('searchHats', () => {
  it('omits color_scope at its default, so the URL carries only what was chosen', async () => {
    const url = sent();
    await searchHats('odysea', false, undefined, 'major');
    expect(url().searchParams.has('color_scope')).toBe(false);
    expect(url().searchParams.get('q')).toBe('odysea');
  });

  it('sends a non-default scope, exact colors and the room', async () => {
    const url = sent();
    await searchHats('blue', true, 4, 'accent');
    expect(url().searchParams.get('color_scope')).toBe('accent');
    expect(url().searchParams.get('exact_colors')).toBe('true');
    expect(url().searchParams.get('room_id')).toBe('4');
  });
});

describe('searchHats — how many matched in all', () => {
  function answering(rows: unknown[], headers: Record<string, string> = {}) {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify(rows), { status: 200, headers: { 'Content-Type': 'application/json', ...headers } },
    )));
  }

  it('reads the uncapped count from X-Total-Count, past the rows returned', async () => {
    // The server stops at its row cap; the header is the only place the rest
    // are counted, and "50 of 50" hid them.
    answering([{ id: 1 }, { id: 2 }], { 'X-Total-Count': '212' });
    expect(await searchHats('shore')).toEqual({ results: [{ id: 1 }, { id: 2 }], total: 212 });
  });

  it('counts the rows themselves when the server sends no count', async () => {
    answering([{ id: 1 }, { id: 2 }]);
    expect((await searchHats('shore')).total).toBe(2);
  });
});

describe('searchHatsByColor', () => {
  it('sends the hex without its #, which the query string would read as a fragment', async () => {
    const url = sent();
    await searchHatsByColor('#1a2b3c');
    expect(url().searchParams.get('hex')).toBe('1a2b3c');
  });
});

describe('getGuestCollection', () => {
  it('omits color_scope at its default here too', async () => {
    const url = sent();
    await getGuestCollection('navy', 'major');
    expect(url().searchParams.has('color_scope')).toBe(false);
  });
});
