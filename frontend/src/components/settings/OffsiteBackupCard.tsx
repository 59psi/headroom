import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getBackupUpload, setBackupUpload, clearBackupUpload, testBackupUpload,
} from '../../api/settings';

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
 * The setup steps are rendered from the server's own description of each
 * provider rather than written here, because they are claims about what the
 * server will run. Every one of them is host-side work that "configured"
 * cannot tell you is missing — which is why the card also reports whether the
 * binary is actually present, and why Test now runs the real thing.
 */
export function OffsiteBackupCard() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ['admin', 'backup-upload'], queryFn: getBackupUpload });
  const [destination, setDestination] = useState('');
  // NOT initialized to a literal. Hardcoding 'rclone' meant that after
  // configuring Synology, reopening Settings showed rclone selected and
  // rclone's setup steps — so the instructions for the provider actually in
  // use were in the payload but unreachable, which reads as "the instructions
  // are gone". `null` means "follow whatever is saved" until a choice is made.
  const [picked, setPicked] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tested, setTested] = useState<{ ok: boolean; detail: string } | null>(null);
  const [showSetup, setShowSetup] = useState(false);

  const invalidate = () => qc.invalidateQueries({ queryKey: ['admin', 'backup-upload'] });

  const save = useMutation({
    mutationFn: () => setBackupUpload(provider, destination.trim()),
    onSuccess: () => { setError(null); setDestination(''); invalidate(); },
    // The server's message names the actual problem ("that is a flag, not a
    // remote"), which is more use than a generic failure.
    onError: (e: Error) => setError(e.message),
  });
  const turnOff = useMutation({ mutationFn: clearBackupUpload, onSuccess: invalidate });
  const test = useMutation({
    mutationFn: testBackupUpload,
    onSuccess: r => { setTested(r); invalidate(); },
  });

  const s = status.data;
  const providers = s?.available_providers ?? [];
  // Saved provider wins until the user picks another, so the steps on screen
  // always describe the transport that is actually configured.
  const provider = picked ?? s?.provider ?? 'rclone';
  const chosen = providers.find(p => p.name === provider);
  const pink = { color: 'var(--neon-pink, #ff4fa3)' };

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Off-site backup</div>
        <p className="text-secondary small mb-3">
          Copies each scheduled backup somewhere else. Rolling backups live on the
          same disk as the data they protect &mdash; which covers a mistake or a
          corrupted database, but not a dead card.
        </p>

        {s && (
          <div className="mb-3">
            {!s.configured ? (
              <p className="small mb-0" style={pink}>
                Not configured &mdash; your only copies are on this machine.
              </p>
            ) : (
              <>
                <p className="small mb-1">
                  <strong>{s.provider ?? 'custom'}</strong>
                  {s.destination && <> &rarr; <code>{s.destination}</code></>}
                  {s.from_environment && (
                    <span className="text-muted"> (set by HEADROOM_BACKUP_UPLOAD_CMD)</span>
                  )}
                </p>
                {/* Configured but the binary is missing is the failure mode that
                    otherwise only shows up as an upload that silently never
                    runs. Worth its own line, in the color of a problem. */}
                {s.binary_available === false && (
                  <p className="small mb-1" style={pink}>
                    That provider&rsquo;s command isn&rsquo;t available inside the
                    container, so no upload can run. See the setup steps below.
                  </p>
                )}
                <p className="text-secondary small mb-0">
                  {s.last_upload_at ? (
                    <>
                      Last upload {new Date(s.last_upload_at).toLocaleString()} &mdash;{' '}
                      {s.last_upload_ok ? 'succeeded' : 'FAILED'}.{' '}
                      {s.upload_successes} ok, {s.upload_failures} failed.
                    </>
                  ) : (
                    // The distinction that matters: configured is not the same
                    // as proven, and only one of them will still be true when
                    // you need the backup.
                    <>Configured, but nothing has been uploaded yet this run. Use <strong>Test now</strong>.</>
                  )}
                </p>
                {s.last_upload_error && (
                  <p className="text-muted small mb-0 font-mono" style={{ fontSize: '0.72rem' }}>
                    {s.last_upload_error}
                  </p>
                )}
              </>
            )}
          </div>
        )}

        {/* Env-configured installs are read-only here on purpose: the browser
            must not be able to override a decision that required host access. */}
        {!s?.from_environment && (
          <>
            <label className="form-label" style={{ fontSize: '0.8rem' }} htmlFor="upload-provider">
              Where to
            </label>
            <select
              id="upload-provider"
              aria-label="Upload provider"
              className="form-control mb-2"
              value={provider}
              onChange={e => { setPicked(e.target.value); setError(null); }}
            >
              {providers.map(p => (
                <option key={p.name} value={p.name}>{p.label}</option>
              ))}
            </select>

            <label className="form-label" style={{ fontSize: '0.8rem' }} htmlFor="upload-dest">
              Destination
            </label>
            <input
              id="upload-dest"
              aria-label="Upload destination"
              className="form-control mb-1"
              placeholder={chosen?.example ?? s?.destination ?? 'box:Headroom'}
              value={destination}
              maxLength={200}
              onChange={e => { setDestination(e.target.value); setError(null); }}
            />
            {chosen && (
              <p className="text-muted small mb-2" style={{ fontSize: '0.72rem' }}>
                Shape: <code>{chosen.destination_hint}</code> &mdash; for example{' '}
                <code>{chosen.example}</code>. This field names the destination; it
                never holds your credentials.
              </p>
            )}

            {chosen && (
              <div className="mb-3">
                <button
                  type="button"
                  className="btn btn-sm btn-outline-primary mb-2"
                  aria-expanded={showSetup}
                  onClick={() => setShowSetup(v => !v)}
                >
                  {showSetup ? 'Hide setup steps' : `How to finish setting up ${chosen.label}`}
                </button>
                {showSetup && (
                  <>
                    <ol className="text-secondary small mb-2" style={{ paddingLeft: '1.1rem' }}>
                      {chosen.setup.map(step => (
                        <li key={step} className="mb-1">{step}</li>
                      ))}
                    </ol>
                    <p className="text-muted small mb-0" style={{ fontSize: '0.72rem' }}>
                      Needs <code>{chosen.binary}</code> in the container:{' '}
                      {chosen.binary_available
                        ? <span>present.</span>
                        : <span style={pink}>not found &mdash; the steps above add it.</span>}
                      {chosen.secret_env && (
                        <> Password comes from <code>{chosen.secret_env}</code> in your{' '}
                        <code>.env</code>, read on the host and never stored here.</>
                      )}
                    </p>
                  </>
                )}
              </div>
            )}

            {error && <p className="small mb-2" style={pink}>{error}</p>}

            <div className="d-flex gap-2 flex-wrap">
              <button
                className="btn btn-primary"
                disabled={!destination.trim() || save.isPending}
                onClick={() => save.mutate()}
              >
                {save.isPending ? 'Saving…' : 'Save'}
              </button>
              {s?.configured && (
                <button
                  className="btn btn-outline-primary"
                  disabled={turnOff.isPending}
                  onClick={() => turnOff.mutate()}
                >
                  Turn off
                </button>
              )}
            </div>
          </>
        )}

        {s?.configured && (
          <div className="mt-3">
            <button
              className="btn btn-outline-primary"
              disabled={test.isPending}
              onClick={() => test.mutate()}
            >
              {test.isPending ? 'Uploading…' : 'Test now'}
            </button>
            <p className="text-muted small mb-0 mt-2" style={{ fontSize: '0.72rem' }}>
              Runs the real upload against your newest backup &mdash; same command,
              same credentials. A dry run would only prove the form was filled in.
            </p>
            {tested && (
              <p className="small mb-0 mt-1" style={tested.ok ? undefined : pink}>
                {tested.detail}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
