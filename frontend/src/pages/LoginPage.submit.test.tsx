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
import { renderWithProviders } from '../test/utils';
import { LoginPage } from './LoginPage';
import * as authApi from '../api/auth';

vi.mock('../api/auth', () => ({
  getAuthStatus: vi.fn(),
  login: vi.fn(),
  setupOwner: vi.fn(),
  passkeyLoginOptions: vi.fn(),
  passkeyLoginVerify: vi.fn(),
}));
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
});
