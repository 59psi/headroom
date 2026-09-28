import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { AccountCard } from './AccountCard';
import * as api from '../../api/auth';
import { ApiError } from '../../api/client';
import * as webauthn from '../../lib/webauthn';
import * as clipboard from '../../lib/clipboard';
import type { PasskeyRead } from '../../types';

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
vi.mock('../../lib/clipboard', () => ({ copyText: vi.fn() }));

const mocked = vi.mocked(api);
const wa = vi.mocked(webauthn);
const copyText = vi.mocked(clipboard.copyText);

/** A registration ceremony's options and its result, as the real shapes. */
function ceremony(stateId: string) {
  return {
    state_id: stateId,
    options: {
      challenge: 'AQID', rp: { name: 'Headroom' },
      user: { id: 'AQ', name: 'owner', displayName: 'owner' }, pubKeyCredParams: [],
    },
  };
}
function credential(id: string) {
  return {
    id, rawId: id, type: 'public-key',
    response: { clientDataJSON: 'AQ', attestationObject: 'Ag' },
    clientExtensionResults: {},
  };
}

const IPHONE: PasskeyRead = { id: 1, name: 'iPhone', created_at: '2026-08-01T12:00:00Z' };
const MAC: PasskeyRead = { id: 2, name: 'MacBook', created_at: '2026-08-02T12:00:00Z' };

describe('AccountCard — too many wrong passwords', () => {
  const LOCKED = 'Too many wrong passwords — try again in a few minutes.';

  it("shows the server's lockout sentence on the token prompt, not a generic wrong-password", async () => {
    const user = userEvent.setup();
    mocked.revealApiToken.mockRejectedValue(new ApiError(LOCKED, 429));
    renderWithProviders(<AccountCard />);

    await user.click(await screen.findByRole('button', { name: 'Show' }));
    await user.type(screen.getByLabelText('Current password to reveal the API token'), 'right-password');
    await user.click(screen.getByRole('button', { name: 'Reveal token' }));

    expect(await screen.findByText(LOCKED)).toBeInTheDocument();
    expect(screen.queryByText(/incorrect/)).not.toBeInTheDocument();
  });

  it('shows it on the password change too', async () => {
    const user = userEvent.setup();
    mocked.changePassword.mockRejectedValue(new ApiError(LOCKED, 429));
    renderWithProviders(<AccountCard />);

    await user.type(await screen.findByLabelText('Current password'), 'right-password');
    await user.type(screen.getByLabelText('New password'), 'a-new-password');
    await user.click(screen.getByRole('button', { name: 'Change password' }));

    expect(await screen.findByText(LOCKED)).toBeInTheDocument();
  });
});

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getMe.mockResolvedValue({ username: 'owner', token_set: true });
  mocked.listPasskeys.mockResolvedValue([]);
  // `clearAllMocks` keeps implementations, so a test that turned passkeys on
  // would leave them on for the next one.
  wa.passkeysSupported.mockReturnValue(false);
});

/** Reveal the token through the password gate, as a person would. */
async function reveal(user: ReturnType<typeof userEvent.setup>, value = 'hr_the-real-token') {
  mocked.revealApiToken.mockResolvedValue({ api_token: value });
  await user.click(await screen.findByRole('button', { name: 'Show' }));
  await user.type(screen.getByLabelText('Current password to reveal the API token'), 'a-strong-password');
  await user.click(screen.getByRole('button', { name: 'Reveal token' }));
  await screen.findByText(value);
}

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
    // The Shortcut holding the old token is now broken; the toast says where.
    expect(await screen.findByText(/API token rotated — update the iOS Shortcut/)).toBeInTheDocument();
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

  it('drops a stale wrong-password error when the prompt is canceled', async () => {
    const user = userEvent.setup();
    mocked.revealApiToken.mockRejectedValue(new Error('Current password is incorrect'));

    renderWithProviders(<AccountCard />);
    await user.click(await screen.findByRole('button', { name: 'Show' }));
    await user.type(screen.getByLabelText('Current password to reveal the API token'), 'wrong');
    await user.click(screen.getByRole('button', { name: 'Reveal token' }));
    await screen.findByText(/password is incorrect/i);

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByText(/password is incorrect/i)).not.toBeInTheDocument();
  });

  it('copies the revealed token — the Share-photos card sends people here for it', async () => {
    const user = userEvent.setup();
    copyText.mockResolvedValue(true);

    renderWithProviders(<AccountCard />);
    // No copy button while the token is masked: there is nothing to copy.
    await screen.findByText('owner');
    expect(screen.queryByRole('button', { name: /copy the api token/i })).not.toBeInTheDocument();

    await reveal(user);
    await user.click(screen.getByRole('button', { name: 'Copy the API token' }));
    expect(copyText).toHaveBeenCalledWith('hr_the-real-token');
  });
});

describe('AccountCard — identity', () => {
  it('leads with who is signed in, and a state for the header', async () => {
    renderWithProviders(<AccountCard />);

    expect(await screen.findByText('owner')).toBeInTheDocument();
    expect(screen.getByText(/Signed in as/)).toBeInTheDocument();
    expect(await screen.findByText('Password only')).toBeInTheDocument();
  });

  it('counts passkeys in the header pill', async () => {
    mocked.listPasskeys.mockResolvedValue([IPHONE, MAC]);
    renderWithProviders(<AccountCard />);

    expect(await screen.findByText('2 passkeys')).toBeInTheDocument();
  });

  it('says so when signing out fails, rather than leaving the button un-pressed', async () => {
    // A bare `await logout()` that rejected left the page in place with no
    // message. (jsdom's `location.assign` cannot be spied on, so the "stay
    // put" half is carried by the mutation's onSuccess-only navigation.)
    const user = userEvent.setup();
    mocked.logout.mockRejectedValue(new Error('Network down'));

    renderWithProviders(<AccountCard />);
    await user.click(await screen.findByRole('button', { name: 'Sign out' }));

    expect(await screen.findByText('Network down')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeEnabled();
  });
});

describe('AccountCard — password', () => {
  it('changes it, clears the fields, and hides the token the server just rotated', async () => {
    // The server rotates the API token as part of a password change, so the
    // value revealed a moment ago is dead — it must not stay on screen to be
    // pasted into the Shortcut.
    const user = userEvent.setup();
    mocked.changePassword.mockResolvedValue(undefined);

    renderWithProviders(<AccountCard />);
    await reveal(user);

    await user.type(screen.getByLabelText('Current password'), 'old-password');
    await user.type(screen.getByLabelText('New password'), 'new-password-123');
    await user.click(screen.getByRole('button', { name: 'Change password' }));

    expect(mocked.changePassword).toHaveBeenCalledWith('old-password', 'new-password-123');
    expect(await screen.findByText(/Password changed/)).toBeInTheDocument();
    expect(screen.getByLabelText('Current password')).toHaveValue('');
    expect(screen.getByLabelText('New password')).toHaveValue('');
    expect(screen.queryByText('hr_the-real-token')).not.toBeInTheDocument();
    expect(screen.getByText('••••••••••••••••')).toBeInTheDocument();
  });

  it('submits on Enter from the new-password field', async () => {
    const user = userEvent.setup();
    mocked.changePassword.mockResolvedValue(undefined);

    renderWithProviders(<AccountCard />);
    await user.type(await screen.findByLabelText('Current password'), 'old-password');
    await user.type(screen.getByLabelText('New password'), 'new-password-123{Enter}');

    expect(mocked.changePassword).toHaveBeenCalledWith('old-password', 'new-password-123');
  });

  it('will not send a new password under eight characters', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AccountCard />);

    await user.type(await screen.findByLabelText('Current password'), 'old-password');
    await user.type(screen.getByLabelText('New password'), 'short{Enter}');

    expect(screen.getByRole('button', { name: 'Change password' })).toBeDisabled();
    expect(mocked.changePassword).not.toHaveBeenCalled();
  });

  it('keeps the error, and what you typed, in place when it fails', async () => {
    const user = userEvent.setup();
    mocked.changePassword.mockRejectedValue(new Error('Current password is incorrect'));

    renderWithProviders(<AccountCard />);
    await user.type(await screen.findByLabelText('Current password'), 'nope');
    await user.type(screen.getByLabelText('New password'), 'new-password-123');
    await user.click(screen.getByRole('button', { name: 'Change password' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Current password is incorrect');
    expect(screen.getByLabelText('New password')).toHaveValue('new-password-123');
    expect(screen.queryByText(/Password changed/)).not.toBeInTheDocument();
  });
});

describe('AccountCard — passkeys', () => {
  it('asks before removing one, and Cancel keeps it', async () => {
    const user = userEvent.setup();
    mocked.listPasskeys.mockResolvedValue([IPHONE]);

    renderWithProviders(<AccountCard />);
    await user.click(await screen.findByRole('button', { name: 'Remove passkey iPhone' }));

    const dialog = screen.getByRole('alertdialog', { name: 'Remove passkey “iPhone”?' });
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    expect(mocked.deletePasskey).not.toHaveBeenCalled();
    expect(screen.getByText('iPhone')).toBeInTheDocument();
  });

  it('takes it off the list at once, before the server answers', async () => {
    const user = userEvent.setup();
    mocked.listPasskeys.mockResolvedValueOnce([IPHONE, MAC]).mockResolvedValue([MAC]);
    let finish!: () => void;
    mocked.deletePasskey.mockReturnValue(new Promise<void>(r => { finish = r; }));

    renderWithProviders(<AccountCard />);
    await user.click(await screen.findByRole('button', { name: 'Remove passkey iPhone' }));
    await user.click(screen.getByRole('button', { name: 'Remove passkey' }));

    expect(mocked.deletePasskey).toHaveBeenCalledWith(1);
    // Still in flight — and already gone.
    await waitFor(() => expect(screen.queryByText('iPhone')).not.toBeInTheDocument());
    expect(screen.getByText('MacBook')).toBeInTheDocument();

    finish();
    expect(await screen.findByText('Passkey “iPhone” removed')).toBeInTheDocument();
  });

  it('puts it back, and says why, when the server refuses', async () => {
    const user = userEvent.setup();
    // The follow-up refetch never answers, so what restores the row can only
    // be the rollback — not a fresh list arriving from the server.
    mocked.listPasskeys
      .mockResolvedValueOnce([IPHONE, MAC])
      .mockReturnValue(new Promise(() => {}));
    mocked.deletePasskey.mockRejectedValue(new Error('Passkey not found'));

    renderWithProviders(<AccountCard />);
    await user.click(await screen.findByRole('button', { name: 'Remove passkey iPhone' }));
    await user.click(screen.getByRole('button', { name: 'Remove passkey' }));

    expect(await screen.findByText('Passkey not found')).toBeInTheDocument();
    expect(screen.getByText('iPhone')).toBeInTheDocument();
    expect(screen.queryByText(/removed/)).not.toBeInTheDocument();
  });

  it('names a new passkey in the in-app dialog', async () => {
    const user = userEvent.setup();
    wa.passkeysSupported.mockReturnValue(true);
    mocked.passkeyRegisterOptions.mockResolvedValue(ceremony('s-1'));
    wa.createPasskey.mockResolvedValue(credential('cred-1'));
    mocked.passkeyRegisterVerify.mockResolvedValue({ ok: true });

    renderWithProviders(<AccountCard />);
    await user.click(await screen.findByRole('button', { name: 'Add passkey' }));

    const dialog = await screen.findByRole('dialog', { name: 'Name this passkey' });
    const field = within(dialog).getByLabelText('Name');
    await user.clear(field);
    await user.type(field, 'iPad');
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(mocked.passkeyRegisterVerify).toHaveBeenCalledWith('s-1', credential('cred-1'), 'iPad'));
    expect(await screen.findByText('Passkey “iPad” added')).toBeInTheDocument();
  });

  it('still registers a passkey whose naming was canceled', async () => {
    // The credential already exists on the device by the time it is named;
    // dropping it on Cancel would leave a passkey the server never accepts.
    const user = userEvent.setup();
    wa.passkeysSupported.mockReturnValue(true);
    mocked.passkeyRegisterOptions.mockResolvedValue(ceremony('s-2'));
    wa.createPasskey.mockResolvedValue(credential('cred-2'));
    mocked.passkeyRegisterVerify.mockResolvedValue({ ok: true });

    renderWithProviders(<AccountCard />);
    await user.click(await screen.findByRole('button', { name: 'Add passkey' }));
    const dialog = await screen.findByRole('dialog', { name: 'Name this passkey' });
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    await waitFor(() =>
      expect(mocked.passkeyRegisterVerify).toHaveBeenCalledWith('s-2', credential('cred-2'), 'Passkey'));
  });

  it('reports a canceled Face ID sheet in place', async () => {
    const user = userEvent.setup();
    wa.passkeysSupported.mockReturnValue(true);
    mocked.passkeyRegisterOptions.mockResolvedValue(ceremony('s-3'));
    wa.createPasskey.mockRejectedValue(new Error('Passkey creation was canceled'));

    renderWithProviders(<AccountCard />);
    await user.click(await screen.findByRole('button', { name: 'Add passkey' }));

    expect(await screen.findByText('Passkey creation was canceled')).toBeInTheDocument();
    expect(mocked.passkeyRegisterVerify).not.toHaveBeenCalled();
  });

  it('gives a refused removal its own reason, not an earlier Add’s', async () => {
    // Both actions share one ErrorNote, which shows the first failure in
    // its list: a canceled Face ID sheet from a minute ago stood in for the
    // server's refusal, so the row came back with the wrong reason beside it.
    const user = userEvent.setup();
    wa.passkeysSupported.mockReturnValue(true);
    mocked.listPasskeys.mockResolvedValue([IPHONE]);
    mocked.passkeyRegisterOptions.mockResolvedValue(ceremony('s-4'));
    wa.createPasskey.mockRejectedValue(new Error('Passkey creation was canceled'));
    mocked.deletePasskey.mockRejectedValue(new Error('Passkey not found'));

    renderWithProviders(<AccountCard />);
    await user.click(await screen.findByRole('button', { name: 'Add passkey' }));
    await screen.findByText('Passkey creation was canceled');

    await user.click(screen.getByRole('button', { name: 'Remove passkey iPhone' }));
    await user.click(screen.getByRole('button', { name: 'Remove passkey' }));

    expect(await screen.findByText('Passkey not found')).toBeInTheDocument();
    expect(screen.queryByText('Passkey creation was canceled')).not.toBeInTheDocument();
    // And the other way round: a fresh Add speaks for itself too.
    await user.click(screen.getByRole('button', { name: 'Add passkey' }));
    expect(await screen.findByText('Passkey creation was canceled')).toBeInTheDocument();
    expect(screen.queryByText('Passkey not found')).not.toBeInTheDocument();
  });

  it('explains, instead of offering, when passkeys cannot work here', async () => {
    renderWithProviders(<AccountCard />);

    expect(await screen.findByText(/Passkeys need HTTPS or localhost/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add passkey' })).not.toBeInTheDocument();
  });
});
