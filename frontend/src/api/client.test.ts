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
import { ApiError, apiFetch, errorMessage } from './client';

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Answer every fetch with `status` and a JSON `detail`. */
function respond(status: number, detail = 'nope') {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(
    JSON.stringify({ detail }),
    { status, headers: { 'Content-Type': 'application/json' } },
  )));
}

/** jsdom's `location.assign` cannot be spied on, so stand in a whole location. */
function at(pathname: string, search = '') {
  const assign = vi.fn();
  vi.stubGlobal('location', { ...window.location, assign, pathname, search });
  return assign;
}

describe('apiFetch on a 401', () => {
  it('sends a signed-out page to the login screen, carrying where it was', async () => {
    const assign = at('/hats/5', '?tab=specs');
    respond(401);
    await expect(apiFetch('/api/hats/5')).rejects.toThrow('Authentication required');
    expect(assign).toHaveBeenCalledWith(`/login?next=${encodeURIComponent('/hats/5?tab=specs')}`);
  });

  it('rejects with an ApiError that keeps the 401, not a bare Error', async () => {
    at('/hats');
    respond(401);
    const err = await apiFetch('/api/hats').catch(e => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(401);
  });

  it('never redirects a public share page, which has no session to lose', async () => {
    const assign = at('/share/tok123');
    respond(401);
    await expect(apiFetch('/api/hats')).rejects.toBeInstanceOf(ApiError);
    expect(assign).not.toHaveBeenCalled();
  });

  it('does not bounce the login page to itself', async () => {
    const assign = at('/login');
    respond(401);
    await expect(apiFetch('/api/hats')).rejects.toBeInstanceOf(ApiError);
    expect(assign).not.toHaveBeenCalled();
  });

  it("passes the auth routes' own 401 through as their message — a wrong password is not a lapsed session", async () => {
    const assign = at('/login');
    respond(401, 'Invalid username or password');
    await expect(apiFetch('/api/auth/login', { method: 'POST' }))
      .rejects.toThrow('Invalid username or password');
    expect(assign).not.toHaveBeenCalled();
  });
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
