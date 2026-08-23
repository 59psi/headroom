import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getBackupUpload, setBackupUpload, clearBackupUpload, testBackupUpload,
} from '../../api/settings';

/**
 * The off-box copy of the backups.
 *
 * The most consequential unknown on a single-box deployment: rolling backups
 * on the same SD card protect against corruption, not against the card. Until
 * this card existed the feature was configurable only through `.env`, and
 * whether it had ever actually run was answerable only by reading container
 * logs.
 *
 * **This form does not accept a command, and that is the point.** The hook
 * runs an argv unattended, as the app user, after every backup — a free-text
 * command field would turn a stolen session into command execution. The
 * browser sends a provider and a destination; the server assembles the argv
 * from a template it owns and rejects anything that isn't `remote:path`.
 */
export function OffsiteBackupCard() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ['admin', 'backup-upload'], queryFn: getBackupUpload });
  const [destination, setDestination] = useState('');
  const [provider, setProvider] = useState('rclone');
  const [error, setError] = useState<string | null>(null);
  const [tested, setTested] = useState<{ ok: boolean; detail: string } | null>(null);

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
              <p className="small mb-0" style={{ color: 'var(--neon-pink, #ff4fa3)' }}>
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
              Provider
            </label>
            <select
              id="upload-provider"
              aria-label="Upload provider"
              className="form-control mb-2"
              value={provider}
              onChange={e => setProvider(e.target.value)}
            >
              {(s?.available_providers ?? ['rclone']).map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>

            <label className="form-label" style={{ fontSize: '0.8rem' }} htmlFor="upload-dest">
              Destination
            </label>
            <input
              id="upload-dest"
              aria-label="Upload destination"
              className="form-control mb-1"
              placeholder={s?.destination ?? 'box:Headroom'}
              value={destination}
              maxLength={200}
              onChange={e => { setDestination(e.target.value); setError(null); }}
            />
            <p className="text-muted small mb-3" style={{ fontSize: '0.72rem' }}>
              An rclone remote and path, e.g. <code>box:Headroom</code>. Configure the
              remote itself with <code>rclone config</code> on the host &mdash; this
              field names it, it does not hold your credentials.
            </p>

            {error && <p className="small mb-2" style={{ color: 'var(--neon-pink, #ff4fa3)' }}>{error}</p>}

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
              <p
                className="small mb-0 mt-1"
                style={{ color: tested.ok ? undefined : 'var(--neon-pink, #ff4fa3)' }}
              >
                {tested.detail}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
