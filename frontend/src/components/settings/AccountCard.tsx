import { useId, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  changePassword, deletePasskey, getMe, listPasskeys, logout,
  passkeyRegisterOptions, passkeyRegisterVerify, revealApiToken, rotateApiToken,
  type PasskeyInfo,
} from '../../api/auth';
import { createPasskey, passkeysSupported } from '../../lib/webauthn';
import { ErrorNote } from '../common/ErrorNote';
import { useConfirm, usePrompt } from '../ui/Dialogs';
import { Panel } from '../ui/Panel';
import { CopyButton } from '../ui/CopyButton';
import { SettingRow } from '../ui/SettingRow';
import { Skeleton } from '../ui/Skeleton';
import { StatusPill } from '../ui/StatusPill';
import { useToast } from '../ui/Toast';

const PASSKEYS_KEY = ['auth', 'passkeys'] as const;

/**
 * Who you are, and every way of proving it: password, passkeys, and the API
 * token the iOS Shortcut sends.
 *
 * Laid out as setting rows — the name of the thing on the left, its controls
 * on the right — because the card used to be four stacked blocks each with a
 * differently styled label, and the one fact everybody looks for first ("am
 * I signed in as the right user?") was a gray line under the title.
 */
export function AccountCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const prompt = usePrompt();
  const uid = useId();
  const me = useQuery({ queryKey: ['auth', 'me'], queryFn: getMe });
  const passkeys = useQuery({ queryKey: PASSKEYS_KEY, queryFn: listPasskeys });
  // The token is no longer part of the profile: `/me` ran on every Settings
  // load, and the value it carried survives logout and session revocation, so
  // a stolen session used to upgrade itself into a permanent credential. It
  // now arrives only from an explicit, password-confirmed request and lives in
  // component state — never in the query cache, which persists across the page
  // and would put it back on every render this change exists to prevent.
  const [token, setToken] = useState<string | null>(null);
  const [tokenPw, setTokenPw] = useState('');
  const [tokenPrompt, setTokenPrompt] = useState<null | 'reveal' | 'rotate'>(null);
  const [curPw, setCurPw] = useState('');
  const [newPw, setNewPw] = useState('');

  const tokenMut = useMutation({
    mutationFn: ({ mode, password }: { mode: 'reveal' | 'rotate'; password: string }) =>
      mode === 'rotate' ? rotateApiToken(password) : revealApiToken(password),
    onSuccess: (res, { mode }) => {
      setToken(res.api_token);
      setTokenPrompt(null);
      setTokenPw('');
      qc.invalidateQueries({ queryKey: ['auth', 'me'] });
      if (mode === 'rotate') toast.success('API token rotated — update the iOS Shortcut');
    },
  });

  function openTokenPrompt(mode: 'reveal' | 'rotate') {
    setTokenPrompt(mode);
    tokenMut.reset();
  }

  function closeTokenPrompt() {
    setTokenPrompt(null);
    setTokenPw('');
    tokenMut.reset();
  }

  const pwMut = useMutation({
    mutationFn: () => changePassword(curPw, newPw),
    onSuccess: () => {
      setCurPw('');
      setNewPw('');
      // The server rotates the API token as part of a password change (a
      // compromise response has to cover the long-lived credential too), so
      // a token revealed above is now dead. Showing it on would invite
      // pasting a value that no longer works into the Shortcut.
      setToken(null);
      qc.invalidateQueries({ queryKey: ['auth', 'me'] });
      toast.success('Password changed — other devices signed out');
    },
  });
  const canChangePw = !!curPw && newPw.length >= 8 && !pwMut.isPending;

  // Optimistic, with the list restored if the server refuses: the result of
  // a DELETE on one row is not in doubt, and a row that lingers for a round
  // trip after you confirmed its removal reads as the click not landing.
  // (This was a bare `await deletePasskey()` in the click handler once, so a
  // failure was an unhandled rejection and the passkey simply stayed in the
  // list with nothing said — the ErrorNote below is what answers that now.)
  const removePasskeyMut = useMutation({
    mutationFn: (p: PasskeyInfo) => deletePasskey(p.id),
    onMutate: async p => {
      await qc.cancelQueries({ queryKey: PASSKEYS_KEY });
      const prev = qc.getQueryData<PasskeyInfo[]>(PASSKEYS_KEY);
      qc.setQueryData<PasskeyInfo[]>(PASSKEYS_KEY, list => list?.filter(x => x.id !== p.id));
      return { prev };
    },
    onError: (_e, _p, ctx) => {
      if (ctx?.prev) qc.setQueryData(PASSKEYS_KEY, ctx.prev);
    },
    onSuccess: (_d, p) => toast.success(`Passkey “${p.name}” removed`),
    // Not returned: the list is already right (or rolled back), so the
    // mutation settles on the DELETE's own answer. Returning the refetch kept
    // it pending until the list came back, holding the error note — and the
    // other rows' Remove buttons — hostage to an unrelated request.
    onSettled: () => { void qc.invalidateQueries({ queryKey: PASSKEYS_KEY }); },
  });

  async function removePasskey(p: PasskeyInfo) {
    const ok = await confirm({
      title: `Remove passkey “${p.name}”?`,
      body: 'That device will no longer sign you in with Face ID / Touch ID. Your password keeps working.',
      confirmLabel: 'Remove passkey',
      tone: 'danger',
    });
    if (!ok) return;
    // One ErrorNote serves both passkey actions and shows the FIRST that
    // failed, so a stale "creation was canceled" from an earlier Add would
    // stand in for this removal's own refusal — the row coming back with the
    // wrong reason beside it. (It was one `pkError` string once, overwritten
    // by whichever failed last.) Only a settled failure is cleared; a pending
    // one keeps its observer so its outcome is still reported.
    if (addPasskeyMut.isError) addPasskeyMut.reset();
    removePasskeyMut.mutate(p);
  }

  const addPasskeyMut = useMutation({
    mutationFn: async () => {
      const { state_id, options } = await passkeyRegisterOptions();
      const credential = await createPasskey(options);
      // By now the credential EXISTS on the authenticator, so canceling the
      // name dialog still registers it — as "Passkey", exactly as the old
      // `prompt(…) || 'Passkey'` did — rather than leaving a passkey on the
      // device that the server has never heard of and will never accept.
      const named = await prompt({
        title: 'Name this passkey',
        label: 'Name',
        placeholder: 'e.g. iPhone',
        defaultValue: 'Passkey',
        confirmLabel: 'Save',
      });
      const name = named?.trim() || 'Passkey';
      await passkeyRegisterVerify(state_id, credential, name);
      return name;
    },
    onSuccess: name => toast.success(`Passkey “${name}” added`),
    onSettled: () => qc.invalidateQueries({ queryKey: PASSKEYS_KEY }),
  });

  const signOutMut = useMutation({
    mutationFn: logout,
    // Only leave once the server has actually dropped the session; a bare
    // `await logout()` that rejected left the page in place with no message.
    onSuccess: () => window.location.assign('/login'),
  });

  const supported = passkeysSupported();
  const keyCount = passkeys.data?.length;
  const username = me.data?.username;

  return (
    <Panel
      title="Account"
      status={keyCount === undefined ? null : keyCount === 0
        ? <StatusPill tone="off" title="No passkeys registered">Password only</StatusPill>
        : <StatusPill tone="ok">{keyCount} passkey{keyCount === 1 ? '' : 's'}</StatusPill>}
      description="Your sign-in: password, Face ID passkeys, and the API token the iOS Shortcut uses."
    >
      <div className="hr-acct-id">
        <span className="hr-acct-avatar" aria-hidden="true">
          {username ? username.charAt(0) : ''}
        </span>
        <div className="hr-acct-who">
          {username ? (
            <span>Signed in as <strong className="font-mono">{username}</strong></span>
          ) : me.isLoading ? (
            <Skeleton lines={1} width="10rem" label="Loading your account…" />
          ) : null}
        </div>
        <button
          type="button"
          className="btn btn-outline-secondary btn-sm"
          onClick={() => signOutMut.mutate()}
          disabled={signOutMut.isPending}
        >
          {signOutMut.isPending ? 'Signing out…' : 'Sign out'}
        </button>
      </div>
      <ErrorNote of={[me, signOutMut]} className="mt-2" />

      <div className="hr-acct-rows">
        <SettingRow
          label="Password"
          hint="Changing it signs out every other device and rotates the API token."
        >
          <form
            className="hr-acct-pw"
            onSubmit={e => {
              e.preventDefault();
              if (canChangePw) pwMut.mutate();
            }}
          >
            <input
              type="password"
              className="form-control"
              placeholder="Current password"
              aria-label="Current password"
              autoComplete="current-password"
              value={curPw}
              onChange={e => setCurPw(e.target.value)}
            />
            <input
              type="password"
              className="form-control"
              placeholder="New password (8+ characters)"
              aria-label="New password"
              autoComplete="new-password"
              value={newPw}
              onChange={e => setNewPw(e.target.value)}
            />
            <button type="submit" className="btn btn-outline-primary" disabled={!canChangePw}>
              {pwMut.isPending ? 'Changing…' : 'Change password'}
            </button>
          </form>
          <ErrorNote of={pwMut} />
        </SettingRow>

        <SettingRow
          label="Passkeys"
          hint={supported
            ? 'Sign in with Face ID or Touch ID instead of typing the password.'
            : 'Passkeys need HTTPS or localhost — browsers only offer them on a trusted connection.'}
        >
          {passkeys.isLoading ? (
            <Skeleton lines={2} />
          ) : (passkeys.data?.length ?? 0) > 0 ? (
            <ul className="hr-acct-keys">
              {passkeys.data!.map(p => (
                <li key={p.id} className="hr-acct-key">
                  <svg className="hr-acct-key-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="8" cy="15" r="4" /><path d="M10.8 12.2 20 3M17 6l3 3M14.5 8.5l2 2" />
                  </svg>
                  <span className="hr-acct-key-text">
                    <span className="hr-acct-key-name">{p.name}</span>
                    <span className="hr-acct-key-date">Added {new Date(p.created_at).toLocaleDateString()}</span>
                  </span>
                  <button
                    type="button"
                    className="btn btn-outline-danger btn-sm"
                    aria-label={`Remove passkey ${p.name}`}
                    onClick={() => removePasskey(p)}
                    disabled={removePasskeyMut.isPending}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          ) : passkeys.data ? (
            <p className="hr-acct-empty">No passkeys yet.</p>
          ) : null}
          {supported && (
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              onClick={() => {
                // As in `removePasskey`: a new attempt clears the other
                // action's settled error so the note speaks for this one.
                if (removePasskeyMut.isError) removePasskeyMut.reset();
                addPasskeyMut.mutate();
              }}
              disabled={addPasskeyMut.isPending}
            >
              {addPasskeyMut.isPending ? 'Adding passkey…' : 'Add passkey'}
            </button>
          )}
          <ErrorNote of={[passkeys, addPasskeyMut, removePasskeyMut]} />
        </SettingRow>

        <SettingRow
          label="API token"
          hint="For the iOS Shortcut — sent as a Bearer header."
        >
          <div className="hr-acct-token" role="group" aria-label="API token">
            <code className="hr-acct-token-value">{token ?? '••••••••••••••••'}</code>
            <div className="hr-acct-token-actions">
              {token && <CopyButton text={token} what="API token" />}
              {token ? (
                <button type="button" className="btn btn-outline-secondary btn-sm" onClick={() => setToken(null)}>
                  Hide
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  onClick={() => openTokenPrompt('reveal')}
                >
                  Show
                </button>
              )}
              <button
                type="button"
                className="btn btn-outline-danger btn-sm"
                onClick={() => openTokenPrompt('rotate')}
              >
                Rotate
              </button>
            </div>
          </div>
          {tokenPrompt && (
            <form
              className="hr-acct-token-form"
              onSubmit={(e) => {
                e.preventDefault();
                tokenMut.mutate({ mode: tokenPrompt, password: tokenPw });
              }}
            >
              <p className="hr-acct-token-note" id={`${uid}-token-note`}>
                {tokenPrompt === 'rotate'
                  ? 'The old token stops working immediately.'
                  : 'This token survives logout, so reading it needs your password.'}
              </p>
              <div className="hr-field-row">
                <input
                  type="password"
                  className="form-control form-control-sm"
                  aria-label={tokenPrompt === 'rotate'
                    ? 'Current password to rotate the API token'
                    : 'Current password to reveal the API token'}
                  aria-describedby={`${uid}-token-note`}
                  placeholder="Current password"
                  autoComplete="current-password"
                  // Straight into the field: the button that opened this form
                  // has no other next step.
                  autoFocus
                  value={tokenPw}
                  onChange={(e) => setTokenPw(e.target.value)}
                />
                <button
                  type="submit"
                  className={`btn btn-sm ${tokenPrompt === 'rotate' ? 'btn-danger' : 'btn-primary'}`}
                  disabled={!tokenPw || tokenMut.isPending}
                >
                  {tokenPrompt === 'rotate' ? 'Rotate token' : 'Reveal token'}
                </button>
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  onClick={closeTokenPrompt}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
          <ErrorNote of={tokenMut} />
        </SettingRow>
      </div>
    </Panel>
  );
}

