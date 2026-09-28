/**
 * Signing in lands on `?next=`, not on Home.
 *
 * `LoginPage.redirect.test.tsx` covers `safeNext`, the sanitizer. Nothing
 * covered the SUBMIT path — and that path did `window.location.assign('/')`
 * for both password and passkey sign-in, honoring `?next=` only through the
 * effect that fires when a visitor arrives already authenticated. A tag tap
 * with an expired session therefore always ended on the home page, having
 * lost the one thing the tap carried.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../test/utils';
import { LoginPage } from './LoginPage';
import * as authApi from '../api/auth';
import * as webauthn from '../lib/webauthn';

vi.mock('../api/auth', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getAuthStatus: vi.fn(),
    login: vi.fn(),
    setupOwner: vi.fn(),
    passkeyLoginOptions: vi.fn(),
    passkeyLoginVerify: vi.fn(),
  };
});
vi.mock('../lib/webauthn', () => ({
  getPasskeyAssertion: vi.fn(),
  passkeysSupported: vi.fn(() => false),
}));

const mocked = vi.mocked(authApi);
const assign = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getAuthStatus.mockResolvedValue({
    authenticated: false, needs_setup: false, guest_view_enabled: false,
  } as never);
  mocked.login.mockResolvedValue(undefined as never);
  // Explicit each time: a test that turns passkeys on must not leave them on
  // for the next (clearing a mock keeps its return value).
  vi.mocked(webauthn.passkeysSupported).mockReturnValue(false);
  vi.stubGlobal('location', { ...window.location, assign, pathname: '/login', search: '' });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('LoginPage submit', () => {
  it('sends a password sign-in on to ?next=', async () => {
    renderWithProviders(<LoginPage />, { route: '/login?next=%2Ft%2Fh%2F42' });

    fireEvent.change(await screen.findByLabelText('Username'), { target: { value: 'brandon' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'hunter2hunter2' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await vi.waitFor(() => expect(assign).toHaveBeenCalledWith('/t/h/42'));
    expect(mocked.login).toHaveBeenCalledWith('brandon', 'hunter2hunter2');
  });

  it('lands on Home when nothing asked for a return', async () => {
    renderWithProviders(<LoginPage />, { route: '/login' });

    fireEvent.change(await screen.findByLabelText('Username'), { target: { value: 'brandon' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'hunter2hunter2' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await vi.waitFor(() => expect(assign).toHaveBeenCalledWith('/'));
  });

  it('never follows an off-site ?next= after sign-in', async () => {
    renderWithProviders(<LoginPage />, { route: '/login?next=https%3A%2F%2Fevil.example%2Fphish' });

    fireEvent.change(await screen.findByLabelText('Username'), { target: { value: 'brandon' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'hunter2hunter2' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await vi.waitFor(() => expect(assign).toHaveBeenCalledWith('/'));
  });

  it('sends a passkey sign-in on to ?next= as well', async () => {
    vi.mocked(webauthn.passkeysSupported).mockReturnValue(true);
    mocked.passkeyLoginOptions.mockResolvedValue({ state_id: 's1', options: {} } as never);
    vi.mocked(webauthn.getPasskeyAssertion).mockResolvedValue({ id: 'cred' });
    mocked.passkeyLoginVerify.mockResolvedValue(undefined as never);
    renderWithProviders(<LoginPage />, { route: '/login?next=%2Ft%2Fh%2F42' });

    fireEvent.click(await screen.findByRole('button', { name: 'Sign in with passkey' }));

    await vi.waitFor(() => expect(assign).toHaveBeenCalledWith('/t/h/42'));
    expect(mocked.passkeyLoginVerify).toHaveBeenCalledWith('s1', { id: 'cred' });
  });
});

describe('LoginPage polish', () => {
  it('does not show a form until it knows which form it is', () => {
    // Sign-in vs claim-the-install depends on the status call; a sign-in form
    // that turns into a setup form under your thumb is worse than a moment of
    // placeholder.
    mocked.getAuthStatus.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<LoginPage />, { route: '/login' });

    expect(screen.getByRole('status')).toHaveTextContent('Loading…');
    expect(screen.queryByLabelText('Username')).toBeNull();
    // The brand holds the card while it waits.
    expect(screen.getByRole('heading', { name: 'Headroom' })).toBeInTheDocument();
  });

  it('reveals the password on request, and hides it again', async () => {
    const user = userEvent.setup();
    renderWithProviders(<LoginPage />, { route: '/login' });
    const field = await screen.findByLabelText('Password');
    const toggle = screen.getByRole('button', { name: 'Show password' });
    expect(field).toHaveAttribute('type', 'password');
    expect(toggle).toHaveAttribute('aria-pressed', 'false');

    await user.click(toggle);
    expect(field).toHaveAttribute('type', 'text');
    expect(toggle).toHaveAttribute('aria-pressed', 'true');

    await user.click(toggle);
    expect(field).toHaveAttribute('type', 'password');
  });

  it('says what it is doing while the sign-in is in flight', async () => {
    mocked.login.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<LoginPage />, { route: '/login' });

    fireEvent.change(await screen.findByLabelText('Username'), { target: { value: 'brandon' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'hunter2hunter2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    const busy = await screen.findByRole('button', { name: 'Signing in…' });
    expect(busy).toBeDisabled();
  });

  it('shows a failed sign-in as an alert', async () => {
    mocked.login.mockRejectedValue(new Error('Invalid username or password'));
    renderWithProviders(<LoginPage />, { route: '/login' });

    fireEvent.change(await screen.findByLabelText('Username'), { target: { value: 'brandon' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrongwrongwrong' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password');
    expect(assign).not.toHaveBeenCalled();
  });

  it('treats a dismissed passkey sheet as a cancel, not a fault', async () => {
    // The browser's own text for this reads like the app broke: "The
    // operation either timed out or was not allowed. See: https://…"
    vi.mocked(webauthn.passkeysSupported).mockReturnValue(true);
    mocked.passkeyLoginOptions.mockResolvedValue({ state_id: 's1', options: {} } as never);
    vi.mocked(webauthn.getPasskeyAssertion).mockRejectedValue(
      new DOMException('The operation either timed out or was not allowed.', 'NotAllowedError'),
    );
    renderWithProviders(<LoginPage />, { route: '/login' });

    fireEvent.click(await screen.findByRole('button', { name: 'Sign in with passkey' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Passkey sign-in was canceled or timed out.');
    expect(mocked.passkeyLoginVerify).not.toHaveBeenCalled();
    // And the button is usable again for a second try.
    expect(screen.getByRole('button', { name: 'Sign in with passkey' })).toBeEnabled();
  });

  it('never blames a passkey for a failed PASSWORD sign-in', async () => {
    // `fetch` rejects with an AbortError of its own when a request is cut
    // off. Mapped through the passkey wording, a password sign-in said
    // "Passkey sign-in was canceled" when no passkey was ever involved.
    mocked.login.mockRejectedValue(new DOMException('The user aborted a request.', 'AbortError'));
    renderWithProviders(<LoginPage />, { route: '/login' });

    fireEvent.change(await screen.findByLabelText('Username'), { target: { value: 'brandon' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'hunter2hunter2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The user aborted a request.');
    expect(alert).not.toHaveTextContent(/passkey/i);
  });

  it('offers guest browsing only when the owner has switched it on', async () => {
    mocked.getAuthStatus.mockResolvedValue({
      authenticated: false, needs_setup: false, guest_view_enabled: true,
    } as never);
    renderWithProviders(<LoginPage />, { route: '/login' });

    const link = await screen.findByRole('link', { name: /Browse the collection as a guest/ });
    expect(link).toHaveAttribute('href', '/guest');
  });
});
