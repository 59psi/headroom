/**
 * `next` arrives in the URL, so it is attacker-controlled by definition.
 *
 * The parameter exists because physical tags need it: tapping an NFC tag with
 * an expired session must come back to that hat rather than dumping you on the
 * home page. But a redirect target that accepts absolute URLs turns the login
 * screen into an open redirect — a link that really is your Headroom login,
 * and really does hand you onward to someone else's page once you've typed
 * your password.
 */
import { describe, expect, it } from 'vitest';
import { safeNext } from './LoginPage';

describe('safeNext', () => {
  it('keeps a same-origin path', () => {
    expect(safeNext('/t/h/42')).toBe('/t/h/42');
    expect(safeNext('/hats?style=a_game')).toBe('/hats?style=a_game');
  });

  it('falls back home when there is nothing to return to', () => {
    expect(safeNext(null)).toBe('/');
    expect(safeNext('')).toBe('/');
  });

  it.each([
    'https://evil.example/phish',
    'http://evil.example',
    // Protocol-relative: no scheme, but a browser reads the host after "//".
    '//evil.example/phish',
    'javascript:alert(1)',
    'evil.example',
    // Backslash variants. A browser treats `\` as `/` in the authority
    // position, so these are protocol-relative to a browser while sailing
    // past a `startsWith('//')` check written against literal characters.
    '/\\evil.example',
    '\\\\evil.example',
    '/\\/evil.example',
    // Whitespace variants. The WHATWG URL parser strips ASCII tab, LF and CR
    // BEFORE it parses, so `/<TAB>/evil.example` passes every check written
    // against the literal characters and the browser navigates to
    // `https://evil.example/`. `params.get('next')` has already decoded
    // `%09`/`%0A`/`%0D` into these by the time the guard sees them.
    '/\t/evil.example',
    '/\n/evil.example',
    '/\r/evil.example',
    '/\t\\evil.example',
    '\t//evil.example',
    '/\t/\t/evil.example',
  ])('refuses to send you off-site: %s', bad => {
    expect(safeNext(bad)).toBe('/');
  });

  it('returns what the browser will actually parse, not the raw string', () => {
    // A same-origin path with a stray tab is not an attack, but it must come
    // back as the browser will read it — with the tab gone — so the check and
    // the navigation cannot disagree about where it leads.
    expect(safeNext('/hats\t/1')).toBe('/hats/1');
    expect(safeNext('/hats?style=a_game#top')).toBe('/hats?style=a_game#top');
  });
});
