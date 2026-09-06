/**
 * A 422 reaches the screen as words, not "[object Object]".
 *
 * FastAPI answers validation failures with `{"detail": [{loc, msg, type}]}`.
 * `apiFetch` did `new Error(body.detail)`, and `String([{…}])` is the literal
 * text "[object Object]" — so every alert built from a mutation's error showed
 * exactly that for every invalid form. The server already strips the echoed
 * input from these bodies (`error_handler.validation_error`); the field name and
 * the reason are what is left, and they are what a person needs.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiFetch, errorMessage } from './client';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('errorMessage', () => {
  it('flattens a validation-error list into field: reason pairs', () => {
    const detail = [
      { type: 'string_too_short', loc: ['body', 'password'], msg: 'String should have at least 8 characters' },
      { type: 'enum', loc: ['body', 'via'], msg: "Input should be 'sold', 'gifted', 'lost', 'trashed' or 'trade'" },
    ];
    expect(errorMessage(detail, 422)).toBe(
      "password: String should have at least 8 characters; via: Input should be 'sold', 'gifted', 'lost', 'trashed' or 'trade'",
    );
  });

  it('passes a plain string detail through', () => {
    expect(errorMessage('Setup already completed', 403)).toBe('Setup already completed');
  });

  it('falls back to the status when there is nothing to say', () => {
    expect(errorMessage(undefined, 502)).toBe('API error 502');
    expect(errorMessage([], 422)).toBe('API error 422');
  });
});

describe('apiFetch on a 422', () => {
  it('throws the readable message, never [object Object]', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ detail: [{ type: 'string_too_short', loc: ['body', 'password'], msg: 'too short' }] }),
      { status: 422, headers: { 'Content-Type': 'application/json' } },
    )));

    await expect(apiFetch('/api/auth/setup', { method: 'POST' })).rejects.toThrow('password: too short');
  });
});
