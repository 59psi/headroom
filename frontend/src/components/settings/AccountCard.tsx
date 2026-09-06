import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  changePassword, deletePasskey, getMe, listPasskeys, logout,
  passkeyRegisterOptions, passkeyRegisterVerify, revealApiToken, rotateApiToken,
} from '../../api/auth';
import { createPasskey, passkeysSupported } from '../../lib/webauthn';

export function AccountCard() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ['auth', 'me'], queryFn: getMe });
  const passkeys = useQuery({ queryKey: ['auth', 'passkeys'], queryFn: listPasskeys });
  // The token is no longer part of the profile: `/me` ran on every Settings
  // load, and the value it carried survives logout and session revocation, so
  // a stolen session used to upgrade itself into a permanent credential. It
  // now arrives only from an explicit, password-confirmed request and lives in
  // component state — never in the query cache, which persists across the page
  // and would put it back on every render this change exists to prevent.
  const [token, setToken] = useState<string | null>(null);
  const [tokenPw, setTokenPw] = useState('');
  const [tokenPrompt, setTokenPrompt] = useState<null | 'reveal' | 'rotate'>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [curPw, setCurPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [pwMsg, setPwMsg] = useState<string | null>(null);
  const [pkError, setPkError] = useState<string | null>(null);

  const tokenMut = useMutation({
    mutationFn: ({ mode, password }: { mode: 'reveal' | 'rotate'; password: string }) =>
      mode === 'rotate' ? rotateApiToken(password) : revealApiToken(password),
    onSuccess: (res) => {
      setToken(res.api_token);
      setTokenPrompt(null);
      setTokenPw('');
      setTokenError(null);
      qc.invalidateQueries({ queryKey: ['auth', 'me'] });
    },
    onError: (e) => setTokenError(String(e instanceof Error ? e.message : e)),
  });

  const pwMut = useMutation({
    mutationFn: () => changePassword(curPw, newPw),
    onSuccess: () => { setPwMsg('Password changed.'); setCurPw(''); setNewPw(''); },
    onError: (e) => setPwMsg(String(e instanceof Error ? e.message : e)),
  });

  // A mutation, like the two above — this was a bare `await deletePasskey()`
  // in the click handler, so a failure was an unhandled rejection and the
  // passkey simply stayed in the list with nothing said.
  const removePasskeyMut = useMutation({
    mutationFn: (id: number) => deletePasskey(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['auth', 'passkeys'] }),
    onError: (e) => setPkError(String(e instanceof Error ? e.message : e)),
  });

  async function addPasskey() {
    setPkError(null);
    try {
      const { state_id, options } = await passkeyRegisterOptions();
      const credential = await createPasskey(options);
      const name = prompt('Name this passkey (e.g. "iPhone")', 'Passkey') || 'Passkey';
      await passkeyRegisterVerify(state_id, credential, name);
      qc.invalidateQueries({ queryKey: ['auth', 'passkeys'] });
    } catch (e) {
      setPkError(String(e instanceof Error ? e.message : e));
    }
  }

  async function signOut() {
    await logout();
    window.location.assign('/login');
  }

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Account</div>
        <p className="text-secondary small mb-3">
          Signed in as <span className="font-mono">{me.data?.username ?? '…'}</span>
        </p>

        <div className="mb-3">
          <div className="hr-metric-label mb-1">API token (for the iOS Shortcut — sent as a Bearer header)</div>
          <div className="d-flex gap-2 flex-wrap align-items-center">
            <code className="small" style={{ wordBreak: 'break-all' }}>
              {token ?? '••••••••••••••••'}
            </code>
            {token ? (
              <button type="button" className="btn btn-outline-secondary btn-sm" onClick={() => setToken(null)}>
                Hide
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                onClick={() => { setTokenPrompt('reveal'); setTokenError(null); }}
              >
                Show
              </button>
            )}
            <button
              type="button"
              className="btn btn-outline-danger btn-sm"
              onClick={() => { setTokenPrompt('rotate'); setTokenError(null); }}
            >
              Rotate
            </button>
          </div>
          {tokenPrompt && (
            <form
              className="d-flex gap-2 flex-wrap align-items-center mt-2"
              onSubmit={(e) => {
                e.preventDefault();
                tokenMut.mutate({ mode: tokenPrompt, password: tokenPw });
              }}
            >
              <input
                type="password"
                className="form-control form-control-sm"
                style={{ maxWidth: '16rem' }}
                aria-label={tokenPrompt === 'rotate'
                  ? 'Current password to rotate the API token'
                  : 'Current password to reveal the API token'}
                placeholder="Current password"
                autoComplete="current-password"
                value={tokenPw}
                onChange={(e) => setTokenPw(e.target.value)}
              />
              <button type="submit" className="btn btn-primary btn-sm" disabled={!tokenPw || tokenMut.isPending}>
                {tokenPrompt === 'rotate' ? 'Rotate token' : 'Reveal token'}
              </button>
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                onClick={() => { setTokenPrompt(null); setTokenPw(''); setTokenError(null); }}
              >
                Cancel
              </button>
              <span className="text-secondary small">
                {tokenPrompt === 'rotate'
                  ? 'The old token stops working immediately.'
                  : 'This token survives logout, so reading it needs your password.'}
              </span>
            </form>
          )}
          {tokenError && <div className="alert alert-danger small mt-2 mb-0">{tokenError}</div>}
        </div>

        <div className="mb-3">
          <div className="hr-metric-label mb-1">Passkeys {passkeysSupported() ? '' : '(needs HTTPS or localhost)'}</div>
          {(passkeys.data ?? []).map(p => (
            <div key={p.id} className="d-flex align-items-center gap-2 small mb-1">
              🔑 {p.name}
              <button
                type="button"
                className="btn btn-link btn-sm p-0"
                style={{ color: 'var(--neon-red)' }}
                onClick={() => {
                  if (confirm(`Remove passkey "${p.name}"?`)) removePasskeyMut.mutate(p.id);
                }}
                disabled={removePasskeyMut.isPending}
              >remove</button>
            </div>
          ))}
          {passkeysSupported() && (
            <button type="button" className="btn btn-outline-secondary btn-sm" onClick={addPasskey}>
              + Add passkey (Face ID / Touch ID)
            </button>
          )}
          {pkError && <div className="alert alert-danger small mt-2 mb-0">{pkError}</div>}
        </div>

        <div className="mb-3">
          <div className="hr-metric-label mb-1">Change password</div>
          <div className="d-flex gap-2 flex-wrap">
            <input type="password" className="form-control" style={{ maxWidth: 200 }} placeholder="Current"
              aria-label="Current password" value={curPw} onChange={e => setCurPw(e.target.value)} autoComplete="current-password" />
            <input type="password" className="form-control" style={{ maxWidth: 200 }} placeholder="New (8+ chars)"
              aria-label="New password" value={newPw} onChange={e => setNewPw(e.target.value)} autoComplete="new-password" />
            <button type="button" className="btn btn-outline-primary"
              disabled={!curPw || newPw.length < 8 || pwMut.isPending}
              onClick={() => pwMut.mutate()}>
              Change
            </button>
          </div>
          {pwMsg && <div className="small mt-1 text-secondary">{pwMsg}</div>}
        </div>

        <button type="button" className="btn btn-outline-danger" onClick={signOut}>
          Sign out
        </button>
      </div>
    </div>
  );
}
