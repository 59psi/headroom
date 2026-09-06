/**
 * Copy works where this app is actually served.
 *
 * `navigator.clipboard` exists only in a secure context, and the plain-HTTP
 * overlay (`docker-compose.http80.yml`) is the path most installs take. Two
 * copy buttons called it bare: on http80 one threw an unhandled rejection and
 * the other silently copied nothing. One routine, one fallback.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { copyText } from './clipboard';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('copyText', () => {
  it('uses the async clipboard in a secure context', async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal('isSecureContext', true);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });

    expect(await copyText('hello')).toBe(true);
    expect(writeText).toHaveBeenCalledWith('hello');
  });

  it('falls back to selection + execCommand over plain HTTP, with no clipboard at all', async () => {
    vi.stubGlobal('isSecureContext', false);
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
    const exec = vi.fn(() => true);
    Object.defineProperty(document, 'execCommand', { value: exec, configurable: true });

    const input = document.createElement('input');
    input.value = 'http://headroom.local/t/h/42';
    document.body.appendChild(input);

    await expect(copyText(input.value, input)).resolves.toBe(true);
    expect(exec).toHaveBeenCalledWith('copy');
    // The text stays selected, so a manual long-press → Copy works too.
    expect(input.selectionStart).toBe(0);
    expect(input.selectionEnd).toBe(input.value.length);
  });

  it('stages the text itself when there is no field to select from', async () => {
    vi.stubGlobal('isSecureContext', false);
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
    const exec = vi.fn(() => true);
    Object.defineProperty(document, 'execCommand', { value: exec, configurable: true });

    await expect(copyText('a share link')).resolves.toBe(true);
    expect(exec).toHaveBeenCalledWith('copy');
    expect(document.querySelector('textarea')).toBeNull(); // cleaned up
  });

  it('reports false rather than throwing when every path refuses', async () => {
    vi.stubGlobal('isSecureContext', true);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn(async () => { throw new Error('denied'); }) },
      configurable: true,
    });

    await expect(copyText('nope')).resolves.toBe(false);
  });
});
