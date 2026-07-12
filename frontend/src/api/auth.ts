import { apiFetch } from './client';

export interface AuthStatus {
  needs_setup: boolean;
  authenticated: boolean;
  username: string | null;
}

export function getAuthStatus() {
  return apiFetch<AuthStatus>('/api/auth/status');
}

export function setupOwner(username: string, password: string) {
  return apiFetch<AuthStatus>('/api/auth/setup', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
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

export function getMe() {
  return apiFetch<{ username: string; api_token: string }>('/api/auth/me');
}

export function rotateApiToken() {
  return apiFetch<{ api_token: string }>('/api/auth/token/rotate', { method: 'POST' });
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

export function createShareLink(label: string, expiresDays?: number) {
  return apiFetch<{ id: number; token: string; url_path: string }>('/api/share-links', {
    method: 'POST',
    body: JSON.stringify({ label, expires_days: expiresDays ?? null }),
  });
}

export function revokeShareLink(id: number) {
  return apiFetch<void>(`/api/share-links/${id}`, { method: 'DELETE' });
}
