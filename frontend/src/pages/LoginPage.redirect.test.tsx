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
  ])('refuses to send you off-site: %s', bad => {
    expect(safeNext(bad)).toBe('/');
  });
});
