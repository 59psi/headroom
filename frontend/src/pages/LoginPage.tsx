import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  getAuthStatus, login, setupOwner,
  passkeyLoginOptions, passkeyLoginVerify,
} from '../api/auth';
import { getPasskeyAssertion, passkeysSupported } from '../lib/webauthn';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

export function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const status = useQuery({ queryKey: ['auth', 'status'], queryFn: getAuthStatus, staleTime: 0 });

  if (status.isLoading) return <LoadingSpinner />;
  if (status.data?.authenticated) {
    navigate('/', { replace: true });
    return null;
  }
  const needsSetup = status.data?.needs_setup ?? false;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (needsSetup && password !== confirm) {
      setError('Passwords do not match');
      return;
    }
    setBusy(true);
    try {
      if (needsSetup) await setupOwner(username.trim(), password);
      else await login(username.trim(), password);
      window.location.assign('/');
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    } finally {
      setBusy(false);
    }
  }

  async function withPasskey() {
    setError(null);
    setBusy(true);
    try {
      const { state_id, options } = await passkeyLoginOptions();
      const credential = await getPasskeyAssertion(options);
      await passkeyLoginVerify(state_id, credential);
      window.location.assign('/');
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="d-flex align-items-center justify-content-center" style={{ minHeight: '100vh', padding: '1rem' }}>
      <div className="card" style={{ width: '100%', maxWidth: 420 }}>
        <div className="card-body">
          <h1 className="mb-1" style={{ fontSize: '1.6rem' }}>HEADROOM</h1>
          <p className="text-secondary small mb-4">
            {needsSetup
              ? 'Welcome! Create the owner account to secure this install.'
              : 'Sign in to your hat vault.'}
          </p>

          <form onSubmit={submit}>
            <div className="mb-3">
              <label className="form-label">Username</label>
              <input
                className="form-control"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
              />
            </div>
            <div className="mb-3">
              <label className="form-label">Password</label>
              <input
                type="password"
                className="form-control"
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete={needsSetup ? 'new-password' : 'current-password'}
              />
              {needsSetup && <div className="form-text small">At least 8 characters</div>}
            </div>
            {needsSetup && (
              <div className="mb-3">
                <label className="form-label">Confirm password</label>
                <input
                  type="password"
                  className="form-control"
                  value={confirm}
                  onChange={e => setConfirm(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
            )}

            {error && <div className="alert alert-danger small">{error}</div>}

            <button
              type="submit"
              className="btn btn-primary w-100 btn-lg"
              disabled={busy || !username.trim() || password.length < 8}
            >
              {busy ? '…' : needsSetup ? 'Create account' : 'Sign in'}
            </button>
          </form>

          {!needsSetup && passkeysSupported() && (
            <button
              type="button"
              className="btn btn-outline-secondary w-100 mt-2"
              onClick={withPasskey}
              disabled={busy}
            >
              🔑 Sign in with passkey
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
