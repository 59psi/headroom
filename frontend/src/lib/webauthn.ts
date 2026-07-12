/**
 * WebAuthn browser plumbing: py_webauthn speaks base64url JSON, the browser
 * API speaks ArrayBuffers. These helpers convert in both directions.
 * Passkeys only work in secure contexts (HTTPS or localhost).
 */

function b64urlToBuf(value: string): ArrayBuffer {
  const pad = '='.repeat((4 - (value.length % 4)) % 4);
  const b64 = (value + pad).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(b64);
  const buf = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
  return buf.buffer;
}

function bufToB64url(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let raw = '';
  for (const b of bytes) raw += String.fromCharCode(b);
  return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function passkeysSupported(): boolean {
  return window.isSecureContext && !!window.PublicKeyCredential;
}

/* eslint-disable @typescript-eslint/no-explicit-any */

export async function createPasskey(options: any): Promise<unknown> {
  const publicKey: any = {
    ...options,
    challenge: b64urlToBuf(options.challenge),
    user: { ...options.user, id: b64urlToBuf(options.user.id) },
    excludeCredentials: (options.excludeCredentials ?? []).map((c: any) => ({
      ...c, id: b64urlToBuf(c.id),
    })),
  };
  const cred = (await navigator.credentials.create({ publicKey })) as any;
  if (!cred) throw new Error('Passkey creation was cancelled');
  return {
    id: cred.id,
    rawId: bufToB64url(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: bufToB64url(cred.response.clientDataJSON),
      attestationObject: bufToB64url(cred.response.attestationObject),
    },
    clientExtensionResults: cred.getClientExtensionResults(),
  };
}

export async function getPasskeyAssertion(options: any): Promise<unknown> {
  const publicKey: any = {
    ...options,
    challenge: b64urlToBuf(options.challenge),
    allowCredentials: (options.allowCredentials ?? []).map((c: any) => ({
      ...c, id: b64urlToBuf(c.id),
    })),
  };
  const cred = (await navigator.credentials.get({ publicKey })) as any;
  if (!cred) throw new Error('Passkey sign-in was cancelled');
  return {
    id: cred.id,
    rawId: bufToB64url(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: bufToB64url(cred.response.clientDataJSON),
      authenticatorData: bufToB64url(cred.response.authenticatorData),
      signature: bufToB64url(cred.response.signature),
      userHandle: cred.response.userHandle ? bufToB64url(cred.response.userHandle) : null,
    },
    clientExtensionResults: cred.getClientExtensionResults(),
  };
}
