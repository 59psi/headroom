import { apiFetch } from './client';

export interface AuthStatus {
  /** Whether to offer "browse as a guest" on the login screen. Rides along on
   *  the one unauthenticated call the page already makes. */
  guest_view_enabled?: boolean;
  needs_setup: boolean;
  authenticated: boolean;
  username: string | null;
}

export function getAuthStatus() {
  return apiFetch<AuthStatus>('/api/auth/status');
}

/**
 * Claim the owner account.
 *
 * `setupToken` is only needed when the deployment sets `HEADROOM_SETUP_TOKEN`,
 * which closes the window where anyone reaching the host first can claim it.
 * Sent only when non-empty so the LAN install, which is the common one, posts
 * exactly the body it always did.
 */
export function setupOwner(username: string, password: string, setupToken?: string) {
  return apiFetch<AuthStatus>('/api/auth/setup', {
    method: 'POST',
    body: JSON.stringify({
      username,
      password,
      ...(setupToken ? { setup_token: setupToken } : {}),
    }),
  });
}

export function login(username: string, password: string) {
  return apiFetch<AuthStatus>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
}

export function logout() {
  return apiFetch<void>('/api/auth/logout', { method: 'POST' });
}

/** Profile only. The bearer token needs the password — see `revealApiToken`. */
export function getMe() {
  return apiFetch<{ username: string; token_set: boolean }>('/api/auth/me');
}

/**
 * The long-lived bearer token, on proof of the password.
 *
 * `/me` used to include it, so every Settings load put a credential that
 * survives logout and session revocation on the wire. Reading it is rare and
 * deliberate; re-authenticating for it costs nothing and stops a stolen
 * session from becoming a permanent one.
 */
export function revealApiToken(currentPassword: string) {
  return apiFetch<{ api_token: string }>('/api/auth/token/reveal', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword }),
  });
}

/** Gated too: rotation RETURNS the new token, so it is the same escalation. */
export function rotateApiToken(currentPassword: string) {
  return apiFetch<{ api_token: string }>('/api/auth/token/rotate', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword }),
  });
}

export function changePassword(currentPassword: string, newPassword: string) {
  return apiFetch<void>('/api/auth/password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

// ------------------------------ passkeys ------------------------------ //

export interface PasskeyInfo {
  id: number;
  name: string;
  created_at: string;
}

export function listPasskeys() {
  return apiFetch<PasskeyInfo[]>('/api/auth/passkeys');
}

export function passkeyRegisterOptions() {
  return apiFetch<{ state_id: string; options: Record<string, unknown> }>(
    '/api/auth/passkeys/register/options', { method: 'POST' },
  );
}

export function passkeyRegisterVerify(stateId: string, credential: unknown, name: string) {
  return apiFetch<{ ok: boolean }>('/api/auth/passkeys/register/verify', {
    method: 'POST',
    body: JSON.stringify({ state_id: stateId, credential, name }),
  });
}

export function deletePasskey(id: number) {
  return apiFetch<void>(`/api/auth/passkeys/${id}`, { method: 'DELETE' });
}

export function passkeyLoginOptions() {
  return apiFetch<{ state_id: string; options: Record<string, unknown> }>(
    '/api/auth/passkeys/login/options', { method: 'POST' },
  );
}

export function passkeyLoginVerify(stateId: string, credential: unknown) {
  return apiFetch<AuthStatus>('/api/auth/passkeys/login/verify', {
    method: 'POST',
    body: JSON.stringify({ state_id: stateId, credential }),
  });
}

// ----------------------------- share links ----------------------------- //

export interface ShareLinkInfo {
  id: number;
  token: string;
  label: string;
  url_path: string;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
}

export function listShareLinks() {
  return apiFetch<ShareLinkInfo[]>('/api/share-links');
}

/**
 * `expiresDays` omitted → the server's default (30 days).
 * `expiresDays: null` → never expires, which the caller has to ask for.
 *
 * The distinction is the whole point and this used to erase it: it sent
 * `expires_days: null` unconditionally, so every link the UI created was
 * permanent and the server-side default could never apply. A share link is
 * unscoped and whole-collection — every hat, with photos, and the room and
 * case it lives in — so a forwarded one is a lasting, room-by-room inventory
 * of valuables. That should be a decision, not what happens when you do not
 * make one.
 */
export function createShareLink(label: string, expiresDays?: number | null) {
  return apiFetch<{ id: number; token: string; url_path: string }>('/api/share-links', {
    method: 'POST',
    body: JSON.stringify({
      label,
      ...(expiresDays === undefined ? {} : { expires_days: expiresDays }),
    }),
  });
}

export function revokeShareLink(id: number) {
  return apiFetch<void>(`/api/share-links/${id}`, { method: 'DELETE' });
}
