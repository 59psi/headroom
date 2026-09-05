import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router';
import {
  getAuthStatus, login, setupOwner,
  passkeyLoginOptions, passkeyLoginVerify,
} from '../api/auth';
import { getPasskeyAssertion, passkeysSupported } from '../lib/webauthn';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

/**
 * Where to go after a successful login.
 *
 * Only same-origin PATHS are honored. `next` reaches us through the URL, so
 * anyone can put anything in it — an absolute URL there would turn the login
 * screen into an open redirect, which is a phishing primitive: a link that
 * genuinely is your Headroom login and genuinely does hand you onward to
 * somebody else's page afterwards. A leading `//` is rejected too, since
 * `//evil.example` is protocol-relative and a browser reads it as a host.
 */
export function safeNext(raw: string | null): string {
  if (!raw) return '/';
  // Backslashes are normalized to forward slashes FIRST. Browsers treat `\` as
  // `/` in the authority position, so `/\evil.example` is protocol-relative to
  // a browser while passing a `startsWith('//')` check written against the
  // literal characters. Not exploitable here — the only consumer is
  // react-router's `navigate()`, which is same-origin by construction — but
  // the guard should hold on its own terms rather than on its caller's.
  const normalized = raw.replace(/\\/g, '/');
  if (!normalized.startsWith('/') || normalized.startsWith('//')) return '/';
  return normalized;
}

export function LoginPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get('next'));
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [setupToken, setSetupToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const status = useQuery({ queryKey: ['auth', 'status'], queryFn: getAuthStatus, staleTime: 0 });

  // Redirecting during render queues a state update in another component
  // mid-render (and runs twice under StrictMode). An effect is the supported
  // place for it.
  const authed = status.data?.authenticated ?? false;
  useEffect(() => {
    if (authed) navigate(next, { replace: true });
  }, [authed, navigate, next]);

  if (status.isLoading) return <LoadingSpinner />;
  if (authed) return null;
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
      if (needsSetup) await setupOwner(username.trim(), password, setupToken.trim());
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
          {/* Public branding logo (auth-gated everywhere else); hides itself
              if no logo is configured so the wordmark stands alone. */}
          <img
            src="/api/public/branding/logo"
            alt=""
            style={{ maxHeight: 56, marginBottom: '0.75rem', display: 'block' }}
            onError={e => { e.currentTarget.style.display = 'none'; }}
          />
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
            {needsSetup && (
              <div className="mb-3">
                <label className="form-label" htmlFor="setup-token">
                  Setup token <span className="text-secondary">(only if configured)</span>
                </label>
                <input
                  id="setup-token"
                  type="password"
                  className="form-control"
                  aria-label="Setup token"
                  value={setupToken}
                  onChange={e => setSetupToken(e.target.value)}
                  autoComplete="off"
                />
                {/* Always shown rather than gated on a flag from the server:
                    publishing "this box wants a setup token" tells an attacker
                    watching for unclaimed installs exactly which ones are worth
                    a try, and the field is harmless to leave blank. */}
                <div className="form-text small">
                  Leave blank unless this deployment sets HEADROOM_SETUP_TOKEN.
                </div>
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

          {/* Only when the owner has switched it on. Absent otherwise — not
              disabled, not explained: a stranger has no reason to learn that
              this install has a guest mode it isn't using. */}
          {!needsSetup && status.data?.guest_view_enabled && (
            <Link
              to="/guest"
              className="btn btn-link w-100 mt-3"
              style={{ color: 'var(--neon-cyan)' }}
            >
              Browse the collection as a guest
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
