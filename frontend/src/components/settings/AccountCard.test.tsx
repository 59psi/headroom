import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { AccountCard } from './AccountCard';
import * as api from '../../api/auth';

vi.mock('../../api/auth', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getMe: vi.fn(),
    listPasskeys: vi.fn(async () => []),
    revealApiToken: vi.fn(),
    rotateApiToken: vi.fn(),
    changePassword: vi.fn(),
    deletePasskey: vi.fn(),
    passkeyRegisterOptions: vi.fn(),
    passkeyRegisterVerify: vi.fn(),
    logout: vi.fn(),
  };
});
vi.mock('../../lib/webauthn', () => ({
  createPasskey: vi.fn(), passkeysSupported: vi.fn(() => false),
}));

const mocked = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getMe.mockResolvedValue({ username: 'owner', token_set: true });
});

describe('AccountCard — the API token is a credential, not a profile field', () => {
  it('does not fetch or show the token on load', async () => {
    renderWithProviders(<AccountCard />);
    await screen.findByText('owner');

    // The card renders on every Settings visit. Before this, that meant a
    // token which survives logout AND session revocation went over the wire
    // each time, so a stolen session upgraded itself into permanent access.
    expect(mocked.revealApiToken).not.toHaveBeenCalled();
    expect(mocked.rotateApiToken).not.toHaveBeenCalled();
    expect(screen.getByText('••••••••••••••••')).toBeInTheDocument();
  });

  it('asks for the password before revealing it', async () => {
    const user = userEvent.setup();
    mocked.revealApiToken.mockResolvedValue({ api_token: 'hr_the-real-token' });

    renderWithProviders(<AccountCard />);
    await user.click(await screen.findByRole('button', { name: 'Show' }));
    await user.type(
      screen.getByLabelText('Current password to reveal the API token'),
      'a-strong-password',
    );
    await user.click(screen.getByRole('button', { name: 'Reveal token' }));

    expect(mocked.revealApiToken).toHaveBeenCalledWith('a-strong-password');
    expect(await screen.findByText('hr_the-real-token')).toBeInTheDocument();
  });

  it('asks for the password before rotating too', async () => {
    // Rotation RETURNS the new token, so gating only reveal would leave the
    // identical escalation open behind a different verb.
    const user = userEvent.setup();
    mocked.rotateApiToken.mockResolvedValue({ api_token: 'hr_brand-new' });

    renderWithProviders(<AccountCard />);
    await user.click(await screen.findByRole('button', { name: 'Rotate' }));
    await user.type(
      screen.getByLabelText('Current password to rotate the API token'),
      'a-strong-password',
    );
    await user.click(screen.getByRole('button', { name: 'Rotate token' }));

    expect(mocked.rotateApiToken).toHaveBeenCalledWith('a-strong-password');
    expect(await screen.findByText('hr_brand-new')).toBeInTheDocument();
  });

  it('surfaces a wrong password instead of silently doing nothing', async () => {
    const user = userEvent.setup();
    mocked.revealApiToken.mockRejectedValue(new Error('Current password is incorrect'));

    renderWithProviders(<AccountCard />);
    await user.click(await screen.findByRole('button', { name: 'Show' }));
    await user.type(
      screen.getByLabelText('Current password to reveal the API token'),
      'wrong',
    );
    await user.click(screen.getByRole('button', { name: 'Reveal token' }));

    expect(await screen.findByText(/password is incorrect/i)).toBeInTheDocument();
    expect(screen.getByText('••••••••••••••••')).toBeInTheDocument();
  });
});
