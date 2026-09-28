import { apiFetch } from './client';
import type {
  ApiTokenRead, AuthStatus, AuthenticationCredentialJSON, CredentialCreationOptionsJSON,
  CredentialRequestOptionsJSON, MeRead, OkRead, PasskeyCeremonyOptions, PasskeyRead,
  RegistrationCredentialJSON,
} from '../types';

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
  return apiFetch<MeRead>('/api/auth/me');
}

/**
 * The long-lived bearer token, on proof of the password.
 *
 * `/me` used to include it, so every Settings load put a credential that
 * survives logout and session revocation on the wire. Reading it is rare and
 * deliberate; re-authenticating for it costs nothing and stops a stolen
 * session from becoming a permanent one.
 *
 * Wrong passwords count against the sign-in limit for this account and
 * address: past it the server answers 429 with a sentence saying so, even to
 * the right password, and the card shows that sentence as it is.
 */
export function revealApiToken(currentPassword: string) {
  return apiFetch<ApiTokenRead>('/api/auth/token/reveal', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword }),
  });
}

/** Gated too: rotation RETURNS the new token, so it is the same escalation. */
export function rotateApiToken(currentPassword: string) {
  return apiFetch<ApiTokenRead>('/api/auth/token/rotate', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword }),
  });
}

/** Same password gate and the same 429 as `revealApiToken`. */
export function changePassword(currentPassword: string, newPassword: string) {
  return apiFetch<void>('/api/auth/password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

// ------------------------------ passkeys ------------------------------ //

export function listPasskeys() {
  return apiFetch<PasskeyRead[]>('/api/auth/passkeys');
}

export function passkeyRegisterOptions() {
  return apiFetch<PasskeyCeremonyOptions<CredentialCreationOptionsJSON>>(
    '/api/auth/passkeys/register/options', { method: 'POST' },
  );
}

export function passkeyRegisterVerify(
  stateId: string, credential: RegistrationCredentialJSON, name: string,
) {
  return apiFetch<OkRead>('/api/auth/passkeys/register/verify', {
    method: 'POST',
    body: JSON.stringify({ state_id: stateId, credential, name }),
  });
}

export function deletePasskey(id: number) {
  return apiFetch<void>(`/api/auth/passkeys/${id}`, { method: 'DELETE' });
}

export function passkeyLoginOptions() {
  return apiFetch<PasskeyCeremonyOptions<CredentialRequestOptionsJSON>>(
    '/api/auth/passkeys/login/options', { method: 'POST' },
  );
}

export function passkeyLoginVerify(stateId: string, credential: AuthenticationCredentialJSON) {
  return apiFetch<AuthStatus>('/api/auth/passkeys/login/verify', {
    method: 'POST',
    body: JSON.stringify({ state_id: stateId, credential }),
  });
}
