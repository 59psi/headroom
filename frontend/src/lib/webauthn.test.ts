/**
 * The WebAuthn conversions, which no test touched: py_webauthn speaks
 * base64url JSON, the browser speaks ArrayBuffers, and a byte lost in
 * between fails only on a real device, as "invalid credential".
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { b64urlToBuf, bufToB64url, createPasskey, getPasskeyAssertion } from './webauthn';

afterEach(() => { vi.unstubAllGlobals(); });

const bytes = (...b: number[]) => new Uint8Array(b).buffer;

describe('base64url', () => {
  it('writes base64url with no padding — the form py_webauthn decodes', () => {
    // 0xfb 0xff encodes to "+/8=" in plain base64.
    expect(bufToB64url(bytes(0xfb, 0xff))).toBe('-_8');
    expect(bufToB64url(bytes(1, 2, 3, 4))).not.toMatch(/=/);
  });

  it('reads unpadded base64url back to the same bytes', () => {
    const original = bytes(0, 1, 250, 251, 252, 253, 254, 255, 42);
    expect(new Uint8Array(b64urlToBuf(bufToB64url(original)))).toEqual(new Uint8Array(original));
  });
});

describe('createPasskey', () => {
  it('hands the browser buffers and sends the server base64url', async () => {
    const create = vi.fn(async () => ({
      id: 'cred-id',
      rawId: bytes(9, 9),
      type: 'public-key',
      response: { clientDataJSON: bytes(1), attestationObject: bytes(2) },
      getClientExtensionResults: () => ({}),
    }));
    vi.stubGlobal('navigator', { ...navigator, credentials: { create } });

    const out = await createPasskey({
      challenge: 'AQID', rp: { name: 'Headroom' },
      user: { id: 'BAU', name: 'owner', displayName: 'owner' },
      pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
      excludeCredentials: [{ id: 'Bgc', type: 'public-key' }],
    });

    const { publicKey } = (create.mock.calls[0] as unknown as [{ publicKey: PublicKeyCredentialCreationOptions }])[0];
    expect(new Uint8Array(publicKey.challenge as ArrayBuffer)).toEqual(new Uint8Array([1, 2, 3]));
    expect(new Uint8Array(publicKey.user.id as ArrayBuffer)).toEqual(new Uint8Array([4, 5]));
    expect(new Uint8Array(publicKey.excludeCredentials![0].id as ArrayBuffer)).toEqual(new Uint8Array([6, 7]));
    expect(out).toEqual({
      id: 'cred-id', rawId: 'CQk', type: 'public-key',
      response: { clientDataJSON: 'AQ', attestationObject: 'Ag' },
      clientExtensionResults: {},
    });
  });

  it('says so when the person cancels', async () => {
    vi.stubGlobal('navigator', { ...navigator, credentials: { create: vi.fn(async () => null) } });
    await expect(createPasskey({
      challenge: 'AQ', rp: { name: 'x' }, user: { id: 'AQ', name: 'a', displayName: 'a' },
      pubKeyCredParams: [],
    })).rejects.toThrow('Passkey creation was canceled');
  });
});

describe('getPasskeyAssertion', () => {
  it('encodes the assertion, and a missing user handle as null', async () => {
    const get = vi.fn(async () => ({
      id: 'cred-id', rawId: bytes(9), type: 'public-key',
      response: {
        clientDataJSON: bytes(1), authenticatorData: bytes(2), signature: bytes(3), userHandle: null,
      },
      getClientExtensionResults: () => ({}),
    }));
    vi.stubGlobal('navigator', { ...navigator, credentials: { get } });

    const out = await getPasskeyAssertion({ challenge: 'AQID', allowCredentials: [] });

    expect(out.response).toEqual({
      clientDataJSON: 'AQ', authenticatorData: 'Ag', signature: 'Aw', userHandle: null,
    });
  });
});
