import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router';
import {
  getAuthStatus, login, setupOwner,
  passkeyLoginOptions, passkeyLoginVerify,
} from '../api/auth';
import { getPasskeyAssertion, passkeysSupported } from '../lib/webauthn';
import { PUBLIC_LOGO_URL } from '../api/public';
import { ErrorNote, describeError } from '../components/common/ErrorNote';
import { Skeleton } from '../components/ui/Skeleton';

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
  // literal characters.
  const normalized = raw.replace(/\\/g, '/');
  if (!normalized.startsWith('/') || normalized.startsWith('//')) return '/';
  // Character checks are not enough on their own: the WHATWG URL parser
  // strips ASCII tab, LF and CR BEFORE it parses, so `/<TAB>/evil.example`
  // passes both tests above and the browser reads it as `//evil.example` — a
  // host. And this IS a real navigation: after login the page calls
  // `window.location.assign(next)`, not react-router. So the last word goes
  // to the parser the browser will use: resolve against our own origin and
  // refuse anything that lands on another one. What comes back is rebuilt
  // from the parsed parts, so the guard and the navigation cannot disagree
  // about where the string leads.
  let url: URL;
  try {
    url = new URL(normalized, window.location.origin);
  } catch {
    return '/';
  }
  if (url.origin !== window.location.origin) return '/';
  const next = url.pathname + url.search + url.hash;
  return next.startsWith('/') && !next.startsWith('//') ? next : '/';
}

/**
 * Words for a failed PASSKEY sign-in.
 *
 * Dismissing the passkey sheet, or letting it time out, rejects with a
 * `NotAllowedError` whose browser text — "The operation either timed out or
 * was not allowed. See: https://www.w3.org/TR/webauthn-2/…" — reads like a
 * fault in the app, when all that happened is that you pressed Cancel.
 *
 * Passkey path only. The password form's failures go out as the server (or
 * the browser) worded them: `fetch` rejects with an `AbortError` of its own
 * when a request is cut off, and "Passkey sign-in was canceled" under a
 * password you just typed would be a wrong answer to a different question.
 */
function describePasskeyError(err: unknown): string {
  if (err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'AbortError')) {
    return 'Passkey sign-in was canceled or timed out.';
  }
  return describeError(err);
}

export function LoginPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get('next'));
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [setupToken, setSetupToken] = useState('');
  // Typing a long password on a phone keyboard, blind, is where most failed
  // sign-ins come from; one tap to check what was typed beats a round trip
  // to the server to find out.
  const [showPassword, setShowPassword] = useState(false);
  // Which path is in flight, so each button can say what IT is waiting for —
  // a single flag put "…" on the password button while the passkey sheet
  // was the thing actually up.
  const [busy, setBusy] = useState<null | 'password' | 'passkey'>(null);
  const [error, setError] = useState<string | null>(null);

  const status = useQuery({ queryKey: ['auth', 'status'], queryFn: getAuthStatus, staleTime: 0 });

  // Redirecting during render queues a state update in another component
  // mid-render (and runs twice under StrictMode). An effect is the supported
  // place for it.
  const authed = status.data?.authenticated ?? false;
  useEffect(() => {
    if (authed) navigate(next, { replace: true });
  }, [authed, navigate, next]);

  if (authed) return null;
  const needsSetup = status.data?.needs_setup ?? false;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (needsSetup && password !== confirm) {
      setError('Passwords do not match');
      return;
    }
    setBusy('password');
    try {
      if (needsSetup) await setupOwner(username.trim(), password, setupToken.trim());
      else await login(username.trim(), password);
      // `next`, not '/'. The effect above honors `?next=` only for a visitor who
      // arrives already signed in; the actual sign-in paths went home, which
      // dropped the one thing a tag tap with an expired session carried —
      // which hat you were holding. `safeNext` has already refused anything
      // off-site, so this is a same-origin path.
      window.location.assign(next);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(null);
    }
  }

  async function withPasskey() {
    setError(null);
    setBusy('passkey');
    try {
      const { state_id, options } = await passkeyLoginOptions();
      const credential = await getPasskeyAssertion(options);
      await passkeyLoginVerify(state_id, credential);
      window.location.assign(next);
    } catch (err) {
      setError(describePasskeyError(err));
    } finally {
      setBusy(null);
    }
  }

  const passwordType = showPassword ? 'text' : 'password';

  return (
    <div className="hr-auth">
      <div className="card hr-feature hr-auth-card">
        <div className="card-body">
          <AuthBrand />

          {/* The card holds its place while the status loads: which form it
              is (sign in, or claim the install) is not known yet, and a
              sign-in form that turns into a setup form under your thumb is
              worse than a moment of placeholder. */}
          {status.isLoading ? (
            <Skeleton lines={4} className="hr-auth-skeleton" />
          ) : (
            <>
              <p className="hr-auth-lead">
                {needsSetup
                  ? 'Welcome! Create the owner account to secure this install.'
                  : 'Sign in to your hat vault.'}
              </p>

              {/* The status call failing is not "no account exists": say so,
                  rather than let the form below look authoritative. */}
              <ErrorNote of={status} what="Couldn't reach the server" className="mb-3" />

              <form onSubmit={submit}>
                <div className="mb-3">
                  <label className="form-label" htmlFor="login-username">Username</label>
                  <input
                    id="login-username"
                    className="form-control"
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    autoComplete="username"
                    // A username is not a sentence. Autocorrect can rewrite
                    // one into the nearest dictionary word on the way to the
                    // server, which then fails as a wrong password. (The
                    // capital a phone adds is harmless — the server
                    // lowercases — but it reads as the field wanting a name.)
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    autoFocus
                  />
                </div>
                <div className="mb-3">
                  <label className="form-label" htmlFor="login-password">Password</label>
                  <div className="hr-password-field">
                    <input
                      id="login-password"
                      type={passwordType}
                      className="form-control"
                      value={password}
                      onChange={e => setPassword(e.target.value)}
                      autoComplete={needsSetup ? 'new-password' : 'current-password'}
                    />
                    <button
                      type="button"
                      className="hr-password-toggle"
                      aria-label="Show password"
                      aria-pressed={showPassword}
                      onClick={() => setShowPassword(v => !v)}
                    >
                      <EyeIcon open={showPassword} />
                    </button>
                  </div>
                  {needsSetup && <div className="form-text">At least 8 characters</div>}
                </div>
                {needsSetup && (
                  <div className="mb-3">
                    <label className="form-label" htmlFor="login-confirm">Confirm password</label>
                    <input
                      id="login-confirm"
                      type={passwordType}
                      className="form-control"
                      value={confirm}
                      onChange={e => setConfirm(e.target.value)}
                      autoComplete="new-password"
                      aria-invalid={error === 'Passwords do not match' || undefined}
                    />
                  </div>
                )}
                {needsSetup && (
                  <div className="mb-3">
                    <label className="form-label" htmlFor="setup-token">
                      Setup token <span className="text-muted">(only if configured)</span>
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
                    <div className="form-text">
                      Leave blank unless this deployment sets HEADROOM_SETUP_TOKEN.
                    </div>
                  </div>
                )}

                {error && <div className="alert alert-danger small mb-3" role="alert">{error}</div>}

                <button
                  type="submit"
                  className="btn btn-primary w-100 btn-lg"
                  disabled={busy !== null || !username.trim() || password.length < 8}
                >
                  {busy === 'password' && <span className="hr-btn-spinner" aria-hidden="true" />}
                  {busy === 'password'
                    ? (needsSetup ? 'Creating account…' : 'Signing in…')
                    : (needsSetup ? 'Create account' : 'Sign in')}
                </button>
              </form>

              {!needsSetup && passkeysSupported() && (
                <>
                  <div className="hr-auth-divider" aria-hidden="true">or</div>
                  <button
                    type="button"
                    className="btn btn-outline-secondary w-100"
                    onClick={withPasskey}
                    disabled={busy !== null}
                  >
                    {busy === 'passkey'
                      ? <span className="hr-btn-spinner" aria-hidden="true" />
                      : <KeyIcon />}
                    {busy === 'passkey' ? 'Waiting for passkey…' : 'Sign in with passkey'}
                  </button>
                </>
              )}

              {/* Only when the owner has switched it on. Absent otherwise — not
                  disabled, not explained: a stranger has no reason to learn that
                  this install has a guest mode it isn't using. */}
              {!needsSetup && status.data?.guest_view_enabled && (
                <div className="hr-auth-foot">
                  <Link to="/guest" className="hr-auth-guest">
                    Browse the collection as a guest
                    <span aria-hidden="true">→</span>
                  </Link>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** Logo over the wordmark. The logo is the public branding route (auth-gated
 *  everywhere else) and removes itself when none is configured, so the
 *  wordmark stands alone rather than under a broken-image box. */
function AuthBrand() {
  const [logoOk, setLogoOk] = useState(true);
  return (
    <div className="hr-auth-brand">
      {logoOk && (
        <img className="hr-auth-logo" src={PUBLIC_LOGO_URL} alt="" onError={() => setLogoOk(false)} />
      )}
      <h1 className="hr-wordmark hr-auth-wordmark">Headroom</h1>
    </div>
  );
}

function EyeIcon({ open }: { open: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
      {open && <path d="M3 3l18 18" />}
    </svg>
  );
}

function KeyIcon() {
  return (
    <svg className="hr-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <circle cx="7.5" cy="15.5" r="4.5" />
      <path d="M10.7 12.3L21 2" />
      <path d="M16 7l3 3" />
      <path d="M18.5 4.5l2 2" />
    </svg>
  );
}
