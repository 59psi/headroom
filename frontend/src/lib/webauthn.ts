/**
 * WebAuthn browser plumbing: py_webauthn speaks base64url JSON, the browser
 * API speaks ArrayBuffers. These helpers convert in both directions.
 * Passkeys only work in secure contexts (HTTPS or localhost).
 *
 * Typed against the DOM's own credential types. This file used to open with a
 * blanket `no-explicit-any` suppression, so the one place the app hands a
 * server-supplied structure to `navigator.credentials` had no type checking at
 * all — a renamed field (`excludeCredentials` vs `exclude_credentials`) would
 * have compiled and failed only on a real device.
 */
import type {
  AuthenticationCredentialJSON, CredentialCreationOptionsJSON, CredentialDescriptorJSON,
  CredentialRequestOptionsJSON, RegistrationCredentialJSON,
} from '../types';

export function b64urlToBuf(value: string): ArrayBuffer {
  const pad = '='.repeat((4 - (value.length % 4)) % 4);
  const b64 = (value + pad).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(b64);
  const buf = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
  return buf.buffer;
}

/** base64url with the padding STRIPPED: py_webauthn's decoder expects none. */
export function bufToB64url(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let raw = '';
  for (const b of bytes) raw += String.fromCharCode(b);
  return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function descriptors(list: CredentialDescriptorJSON[] | undefined): PublicKeyCredentialDescriptor[] {
  return (list ?? []).map(c => ({ ...c, id: b64urlToBuf(c.id) }));
}

export function passkeysSupported(): boolean {
  return window.isSecureContext && !!window.PublicKeyCredential;
}

export async function createPasskey(options: CredentialCreationOptionsJSON): Promise<RegistrationCredentialJSON> {
  const publicKey: PublicKeyCredentialCreationOptions = {
    ...options,
    challenge: b64urlToBuf(options.challenge),
    user: { ...options.user, id: b64urlToBuf(options.user.id) },
    excludeCredentials: descriptors(options.excludeCredentials),
  };
  const cred = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential | null;
  if (!cred) throw new Error('Passkey creation was canceled');
  const response = cred.response as AuthenticatorAttestationResponse;
  return {
    id: cred.id,
    rawId: bufToB64url(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: bufToB64url(response.clientDataJSON),
      attestationObject: bufToB64url(response.attestationObject),
    },
    clientExtensionResults: cred.getClientExtensionResults(),
  };
}

export async function getPasskeyAssertion(options: CredentialRequestOptionsJSON): Promise<AuthenticationCredentialJSON> {
  const publicKey: PublicKeyCredentialRequestOptions = {
    ...options,
    challenge: b64urlToBuf(options.challenge),
    allowCredentials: descriptors(options.allowCredentials),
  };
  const cred = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential | null;
  if (!cred) throw new Error('Passkey sign-in was canceled');
  const response = cred.response as AuthenticatorAssertionResponse;
  return {
    id: cred.id,
    rawId: bufToB64url(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: bufToB64url(response.clientDataJSON),
      authenticatorData: bufToB64url(response.authenticatorData),
      signature: bufToB64url(response.signature),
      userHandle: response.userHandle ? bufToB64url(response.userHandle) : null,
    },
    clientExtensionResults: cred.getClientExtensionResults(),
  };
}
