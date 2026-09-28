import { useEffect, useId, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getBackupUpload, setBackupUpload, clearBackupUpload, testBackupUpload,
} from '../../api/settings';
import type { BackupUploadProvider, BackupUploadStatus } from '../../types';
import { timeAgo } from '../../lib/format';
import { qk } from '../../lib/queryKeys';
import { ErrorNote } from '../common/ErrorNote';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';
import { useConfirm } from '../ui/Dialogs';

const STATUS_KEY = qk.admin.backupUpload();

/**
 * The off-box copy's state in one word.
 *
 * "Configured" is deliberately NOT one of the words: configured is not the
 * same as working, and only one of them will still be true on the day you
 * need the backup. Ranked worst-first — a missing binary means no upload can
 * run at all, which outranks a failure that the next attempt might clear.
 */
function UploadPill({ s, testing }: { s: BackupUploadStatus; testing: boolean }) {
  if (testing) return <StatusPill tone="busy">Uploading</StatusPill>;
  if (!s.configured) {
    return <StatusPill tone="warn" title="Your only copies are on this machine.">Not set</StatusPill>;
  }
  if (s.binary_available === false) return <StatusPill tone="error">Can’t run</StatusPill>;
  if (s.last_upload_at && s.last_upload_ok === false) return <StatusPill tone="error">Failing</StatusPill>;
  if (!s.last_upload_at) return <StatusPill tone="warn">Untested</StatusPill>;
  return <StatusPill tone="ok">Working</StatusPill>;
}

/**
 * The host-side steps for one provider.
 *
 * Rendered from the server's own description of each provider rather than
 * written here, because they are claims about what the server will run. Every
 * one of them is host-side work that "configured" cannot tell you is missing —
 * which is why the card also reports whether the binary is actually present.
 */
function SetupSteps({
  p, open, onToggle,
}: { p: BackupUploadProvider; open: boolean; onToggle: () => void }) {
  const bodyId = useId();
  return (
    <div className="hr-upkeep-setup">
      <button
        type="button"
        className="btn btn-sm btn-outline-secondary"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={onToggle}
      >
        {open ? 'Hide setup steps' : `How to finish setting up ${p.label}`}
      </button>
      {open && (
        <div className="hr-upkeep-setup-body" id={bodyId}>
          <ol className="hr-upkeep-steps">
            {p.setup.map(step => <li key={step}>{step}</li>)}
          </ol>
          <p className="hr-upkeep-fine">
            Needs <code>{p.binary}</code> in the container:{' '}
            {p.binary_available
              ? <span>present.</span>
              : <span className="hr-upkeep-bad-text">not found — the steps above add it.</span>}
            {p.secret_env && (
              <> Password comes from <code>{p.secret_env}</code> in your{' '}
              <code>.env</code>, read on the host and never stored here.</>
            )}
          </p>
        </div>
      )}
    </div>
  );
}

/**
 * The off-box copy of the backups.
 *
 * The most consequential unknown on a single-box deployment: rolling backups
 * on the same SD card protect against corruption, not against the card.
 *
 * **This form does not accept a command, and that is the point.** The hook
 * runs an argv unattended, as the app user, after every backup — a free-text
 * command field would turn a stolen session into command execution. The
 * browser sends a provider and a destination; the server assembles the argv
 * from a template it owns and rejects anything that isn't the shape that
 * provider documents.
 *
 * Once a destination is saved the card leads with what it is and whether it
 * works, and the form folds behind "Change destination": changing where the
 * backups go is a once-a-year errand, and the fields for it were most of the
 * card's height on every visit in between. Unconfigured, the card IS the form.
 */
export function OffsiteBackupCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const formId = useId();
  const status = useQuery({ queryKey: STATUS_KEY, queryFn: getBackupUpload });
  const [destination, setDestination] = useState('');
  // NOT initialized to a literal. Hardcoding 'rclone' meant that after
  // configuring Synology, reopening Settings showed rclone selected and
  // rclone's setup steps — so the instructions for the provider actually in
  // use were in the payload but unreachable, which reads as "the instructions
  // are gone". `null` means "follow whatever is saved" until a choice is made.
  const [picked, setPicked] = useState<string | null>(null);
  const [tested, setTested] = useState<{ ok: boolean; detail: string } | null>(null);
  const [showSetup, setShowSetup] = useState(false);
  const [editing, setEditing] = useState(false);

  // Cancel, Save and Turn off each unmount the very button that was pressed —
  // the form folds away, or the card flips to the unconfigured form — and a
  // focused element that is removed drops keyboard focus to <body>, throwing
  // a keyboard or screen-reader user back to the top of the page. So each of
  // them names the control that leads the card afterwards, and focus goes
  // there once it has rendered. Only if focus was actually lost, though: a
  // save that lands after the person has moved on must not pull them back.
  const refocus = useRef<'change' | 'provider' | null>(null);
  const changeRef = useRef<HTMLButtonElement>(null);
  const providerRef = useRef<HTMLSelectElement>(null);
  useEffect(() => {
    if (!refocus.current) return;
    const target = refocus.current === 'change' ? changeRef.current : providerRef.current;
    // Not on screen yet — the state that shows it can land a render later
    // than the one that hid the pressed button (the cache write vs. setState).
    if (!target) return;
    refocus.current = null;
    const active = document.activeElement;
    if (!active || active === document.body) target.focus();
  });

  // The PUT and DELETE both answer with the full status, so the card shows
  // the new state the moment the server accepts it instead of after a second
  // round trip; the invalidate that follows is the belt to that brace. The
  // activity log is refreshed too — it sits on the same tab, and saving and
  // clearing both write an entry to it.
  const applyStatus = (next: BackupUploadStatus) => {
    qc.setQueryData(STATUS_KEY, next);
    qc.invalidateQueries({ queryKey: STATUS_KEY });
    qc.invalidateQueries({ queryKey: qk.admin.activity() });
  };

  const save = useMutation({
    mutationFn: () => setBackupUpload(provider, destination.trim()),
    onSuccess: next => {
      refocus.current = 'change';
      applyStatus(next);
      setDestination('');
      setEditing(false);
      setTested(null);
      toast.success('Off-site backup saved');
    },
    // The server's message names the actual problem ("that is a flag, not a
    // remote"), which is more use than a generic failure — ErrorNote shows it
    // verbatim, and typing again clears it.
  });
  const turnOff = useMutation({
    mutationFn: clearBackupUpload,
    onSuccess: next => {
      refocus.current = 'provider';
      applyStatus(next);
      setTested(null);
      setPicked(null);
      setEditing(false);
      toast.success('Off-site backup turned off');
    },
  });
  const test = useMutation({
    mutationFn: testBackupUpload,
    onSuccess: r => {
      setTested(r);
      qc.invalidateQueries({ queryKey: STATUS_KEY });
      // A failure is reported in place, where it stays readable — the detail
      // is often several lines of "here is what to fix". Only the good news
      // gets a toast.
      if (r.ok) toast.success('Test upload finished');
    },
  });

  const s = status.data;
  const providers = s?.available_providers ?? [];
  // Saved provider wins until the user picks another, so the steps on screen
  // always describe the transport that is actually configured.
  //
  // `||`, not `??`: Turn off stores the provider as "" rather than deleting
  // it, so after a turn-off every status reads `provider: ""`. With `??` that
  // empty string won — the select matched no option, the shape hint and
  // setup steps vanished, and Save sent `provider: ""` for the server to
  // reject. Turn off now lands straight on the form, so that was the very
  // next thing anyone would do.
  const provider = picked || s?.provider || 'rclone';
  const chosen = providers.find(p => p.name === provider);
  const configured = !!s?.configured;
  // Env-configured installs are read-only here on purpose: the browser must
  // not be able to override a decision that required host access.
  const canEdit = !!s && !s.from_environment;
  const formOpen = canEdit && (!configured || editing);
  const savedLabel = providers.find(p => p.name === s?.provider)?.label
    ?? (s?.provider && s.provider !== 'custom' ? s.provider : 'Custom command');

  function cancelEdit() {
    refocus.current = 'change';
    setEditing(false);
    setPicked(null);
    setDestination('');
    save.reset();
  }

  async function askTurnOff() {
    const ok = await confirm({
      title: 'Turn off off-site backup?',
      // A string, not markup: outside a DialogProvider the fallback is
      // `window.confirm`, which can only carry text — an element body would
      // ask the bare question without the consequence.
      body:
        'Scheduled backups keep running, but from now on every copy stays on '
        + 'this machine. The destination is forgotten; you can set it up again '
        + 'at any time.',
      confirmLabel: 'Turn off',
      tone: 'danger',
    });
    if (ok) turnOff.mutate();
  }

  const setup = chosen && canEdit && (
    <SetupSteps p={chosen} open={showSetup} onToggle={() => setShowSetup(v => !v)} />
  );

  // Every footer button is KEYED. The two footers are the same fragment shape,
  // so unkeyed React reused each <button> by position: the Save node became
  // "Test now" and Cancel became "Change destination", focus and all — a
  // second Enter after Save ran a real upload nobody asked for. Keyed, a
  // button that goes away is really gone, and `refocus` above decides where
  // focus lands instead of the reconciler.
  let footer = null;
  if (formOpen) {
    footer = (
      <>
        <button
          key="save"
          type="submit"
          form={formId}
          className="btn btn-primary"
          disabled={!destination.trim() || save.isPending}
        >
          {save.isPending ? 'Saving…' : 'Save'}
        </button>
        {configured && (
          <button key="cancel" type="button" className="btn btn-outline-secondary" onClick={cancelEdit}>
            Cancel
          </button>
        )}
      </>
    );
  } else if (configured) {
    footer = (
      <>
        <button
          key="test"
          type="button"
          className="btn btn-primary"
          disabled={test.isPending}
          onClick={() => test.mutate()}
        >
          {test.isPending ? 'Uploading…' : 'Test now'}
        </button>
        {canEdit && (
          <button
            key="change"
            ref={changeRef}
            type="button"
            className="btn btn-outline-secondary"
            onClick={() => setEditing(true)}
          >
            Change destination
          </button>
        )}
        {canEdit && (
          <button
            key="turn-off"
            type="button"
            className="btn btn-outline-danger"
            disabled={turnOff.isPending}
            onClick={askTurnOff}
          >
            {turnOff.isPending ? 'Turning off…' : 'Turn off'}
          </button>
        )}
        <p key="note" className="hr-upkeep-foot-note">
          Test now runs the real upload against your newest backup — same
          command, same credentials.
        </p>
      </>
    );
  }

  return (
    <Panel
      title="Off-site backup"
      className="hr-upkeep-card"
      status={s && <UploadPill s={s} testing={test.isPending} />}
      description="Copies each scheduled backup somewhere other than the disk it protects."
      help={
        <>
          <p>
            Rolling backups live on the same disk as the data they protect —
            which covers a mistake or a corrupted database, but not a dead card.
            This sends a copy of each one somewhere else after it is written.
          </p>
          <p>
            The destination field only names where the archive goes; your
            credentials stay in the provider’s own configuration on the host.
            <strong> Test now</strong> runs the real upload, because a dry run
            would only prove the form was filled in.
          </p>
        </>
      }
      footer={footer}
    >
      {status.isPending ? (
        <Skeleton lines={3} />
      ) : (
        <>
          <ErrorNote of={[status, turnOff]} className="mb-3" />

          {s && !s.configured && (
            // Yellow, like the "Not set" pill above it: a choice not made yet,
            // not something that broke.
            <p className="hr-upkeep-alert is-warn">
              Not configured — your only copies are on this machine.
            </p>
          )}

          {s?.configured && (
            <div className="hr-upkeep-summary">
              <div className="hr-upkeep-dest">
                <span className="hr-upkeep-dest-provider">{savedLabel}</span>
                {s.destination && <code className="hr-upkeep-dest-path">{s.destination}</code>}
              </div>
              {s.from_environment && (
                <p className="hr-upkeep-fine">
                  Set by <code>HEADROOM_BACKUP_UPLOAD_CMD</code> on the host, so it
                  can’t be changed from here.
                </p>
              )}
              {/* Configured but the binary is missing is the failure mode that
                  otherwise only shows up as an upload that silently never
                  runs. Worth its own line, in the color of a problem. */}
              {s.binary_available === false && (
                <p className="hr-upkeep-bad-text">
                  That provider’s command isn’t available inside the container,
                  so no upload can run.{setup ? ' See the setup steps below.' : ''}
                </p>
              )}
              {/* State the actual state. A backup report that says "never"
                  when the archive shipped last night is worse than none, and
                  "yet this run" was an implementation detail leaking into the
                  one line that has to be trustworthy. WHEN and WHICH ARCHIVE
                  are both on screen: "it ran" is not an answer anyone can act
                  on. */}
              {s.last_upload_at ? (
                <div className="hr-upkeep-last">
                  <p className="mb-0">
                    <span className={s.last_upload_ok ? 'hr-upkeep-ok-text' : 'hr-upkeep-bad-text'}>
                      {s.last_upload_ok ? 'Last uploaded' : 'Last attempt failed'}
                    </span>{' '}
                    <time dateTime={s.last_upload_at}>{timeAgo(s.last_upload_at)}</time>
                    <span className="text-muted"> · {new Date(s.last_upload_at).toLocaleString()}</span>
                  </p>
                  {s.last_upload_name && (
                    <p className="font-mono hr-upload-file hr-upkeep-archive">{s.last_upload_name}</p>
                  )}
                  <p className="hr-upkeep-fine">
                    {s.upload_successes} uploaded, {s.upload_failures} failed so far.
                  </p>
                </div>
              ) : (
                // Reached only when nothing has EVER uploaded — this record
                // is persisted, so it no longer resets on restart.
                <p className="hr-upkeep-note mb-0">
                  Configured, but nothing has ever been uploaded. Use <strong>Test now</strong>.
                </p>
              )}
              {s.last_upload_error && <p className="hr-upkeep-error-text">{s.last_upload_error}</p>}
            </div>
          )}

          {tested && (
            <p className={`hr-upkeep-result ${tested.ok ? 'is-ok' : 'is-bad'}`}>
              {tested.detail}
            </p>
          )}
          <ErrorNote of={test} what="Test did not run" className="mb-3" />

          {/* The setup steps for the SAVED provider, reachable without opening
              the form — the missing-binary line above points here. */}
          {configured && !formOpen && setup}

          {/* Stated HERE, not only in the tarball's README. The README is inside
              the archive, so it is read after the decision it is warning about
              has already been made and repeated nightly. This is the screen
              where someone types a cloud destination — so it stays in plain
              sight rather than folded into "How this works". */}
          <div className="alert alert-warning hr-upkeep-warning">
            <strong>Use an encrypting remote.</strong> The archive is the whole
            database, which holds your <strong>API keys in plaintext</strong>,
            your live API token, live session ids, share-link tokens and your
            password hash — plus Caddy’s <strong>CA private key</strong> if you
            run the LAN-HTTPS overlay. Headroom does not encrypt it, so whoever
            can read your cloud account can read all of that. With rclone that
            is a <code>crypt</code> remote and no code change; see OPERATIONS §4.
            Keep the passphrase somewhere that is not this backup.
          </div>

          {formOpen && (
            <form
              id={formId}
              className="hr-upkeep-form"
              onSubmit={e => {
                e.preventDefault();
                if (destination.trim() && !save.isPending) save.mutate();
              }}
            >
              {configured && <span className="hr-eyebrow">New destination</span>}
              <div className="hr-upkeep-fields">
                <div>
                  <label className="form-label" htmlFor="upload-provider">Provider</label>
                  <select
                    ref={providerRef}
                    id="upload-provider"
                    aria-label="Upload provider"
                    className="form-select"
                    value={provider}
                    onChange={e => { setPicked(e.target.value); save.reset(); }}
                  >
                    {providers.map(p => (
                      <option key={p.name} value={p.name}>{p.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="form-label" htmlFor="upload-dest">Destination</label>
                  <input
                    id="upload-dest"
                    aria-label="Upload destination"
                    className="form-control"
                    placeholder={chosen?.example ?? s?.destination ?? 'box:Headroom'}
                    value={destination}
                    maxLength={200}
                    autoComplete="off"
                    autoCapitalize="off"
                    spellCheck={false}
                    // Opening the form is asking to type here; an unconfigured
                    // card, open from the start, does not steal focus on load.
                    autoFocus={editing}
                    onChange={e => { setDestination(e.target.value); if (save.isError) save.reset(); }}
                  />
                </div>
              </div>
              {chosen && (
                <p className="form-text">
                  Shape: <code>{chosen.destination_hint}</code> — for example{' '}
                  <code>{chosen.example}</code>. This field names the destination;
                  it never holds your credentials.
                </p>
              )}
              {setup}
              <ErrorNote of={save} what="Not saved" className="mt-2" />
            </form>
          )}
        </>
      )}
    </Panel>
  );
}
