import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  changePassword, deletePasskey, getMe, listPasskeys, logout,
  passkeyRegisterOptions, passkeyRegisterVerify, rotateApiToken,
} from '../../api/auth';
import { createPasskey, passkeysSupported } from '../../lib/webauthn';

export function AccountCard() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ['auth', 'me'], queryFn: getMe });
  const passkeys = useQuery({ queryKey: ['auth', 'passkeys'], queryFn: listPasskeys });
  const [showToken, setShowToken] = useState(false);
  const [curPw, setCurPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [pwMsg, setPwMsg] = useState<string | null>(null);
  const [pkError, setPkError] = useState<string | null>(null);

  const rotateMut = useMutation({
    mutationFn: rotateApiToken,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['auth', 'me'] }),
  });

  const pwMut = useMutation({
    mutationFn: () => changePassword(curPw, newPw),
    onSuccess: () => { setPwMsg('Password changed.'); setCurPw(''); setNewPw(''); },
    onError: (e) => setPwMsg(String(e instanceof Error ? e.message : e)),
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
              {showToken ? me.data?.api_token : '••••••••••••••••'}
            </code>
            <button type="button" className="btn btn-outline-secondary btn-sm" onClick={() => setShowToken(!showToken)}>
              {showToken ? 'Hide' : 'Show'}
            </button>
            <button
              type="button"
              className="btn btn-outline-danger btn-sm"
              onClick={() => { if (confirm('Rotate token? The old one stops working immediately.')) rotateMut.mutate(); }}
            >
              Rotate
            </button>
          </div>
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
                onClick={async () => {
                  if (confirm(`Remove passkey "${p.name}"?`)) {
                    await deletePasskey(p.id);
                    qc.invalidateQueries({ queryKey: ['auth', 'passkeys'] });
                  }
                }}
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
              value={curPw} onChange={e => setCurPw(e.target.value)} autoComplete="current-password" />
            <input type="password" className="form-control" style={{ maxWidth: 200 }} placeholder="New (8+ chars)"
              value={newPw} onChange={e => setNewPw(e.target.value)} autoComplete="new-password" />
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
