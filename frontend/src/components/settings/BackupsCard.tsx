import { useQuery } from '@tanstack/react-query';
import { ErrorNote } from '../common/ErrorNote';
import { listBackups, backupDownloadUrl, getBackupHealth } from '../../api/settings';
import type { BackupHealth } from '../../types';
import { formatBytes, timeAgo } from '../../lib/format';

/**
 * Is the scheduler working — which the file list cannot answer.
 *
 * A scheduler that died three weeks ago and one that ran this morning produce
 * an identical inventory, and in both cases the newest file is the last
 * success. The endpoint that answers this has existed since 2.26 and nothing
 * rendered it, so the question stayed unanswerable outside curl.
 */
function SchedulerStatus({ h }: { h: BackupHealth }) {
  if (!h.enabled) {
    return (
      <p className="text-muted small mb-2">
        Scheduled backups are switched off for this deployment.
      </p>
    );
  }

  // Ranked worst-first: a stopped task outranks a failure count, because no
  // further attempt is coming to change it.
  const problem = !h.running
    ? 'The scheduler is not running — no further backups will be written until restart.'
    : h.consecutive_failures > 0
      ? `${h.consecutive_failures} backup${h.consecutive_failures === 1 ? '' : 's'} in a row failed.`
      : null;

  return (
    <div className="mb-3">
      <p className="small mb-1" style={{ color: problem ? 'var(--neon-pink)' : undefined }}>
        {problem ?? 'Scheduler healthy.'}{' '}
        <span className="text-secondary">
          Last backup {timeAgo(h.last_success_at)}
          {/* Derived means a file exists, not that a run was recorded — the
              in-memory record is process-local and a restart clears it. */}
          {h.last_success_derived && ' (from the file on disk — this process has not run one yet)'}
          .
        </span>
      </p>
      {h.last_skip_reason && !problem && (
        <p className="text-secondary small mb-0">
          {h.last_skip_reason} Backups are only written when something has
          changed, so an unchanged collection keeps the snapshot it already has
          rather than spending a slot restating it.
        </p>
      )}
      {h.last_error && (
        <p className="text-muted small mb-0 font-mono" style={{ fontSize: '0.72rem' }}>
          {h.last_error}
        </p>
      )}
    </div>
  );
}

export function BackupsCard() {
  const backups = useQuery({ queryKey: ['admin', 'backups'], queryFn: listBackups });
  const health = useQuery({ queryKey: ['admin', 'backup-health'], queryFn: getBackupHealth });

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Backups</div>
        <p className="text-secondary small mb-3">
          Backups are gzipped tarballs of <code>/data</code>. Scheduled rolling
          backups run inside the container and are kept under <code>/data/backups/</code>.
          Use <strong>DB only</strong> when the photo tree is large and you only
          need the metadata captured (photos are JPEG/PNG so they barely compress
          anyway).
        </p>

        {health.data && <SchedulerStatus h={health.data} />}
        <ErrorNote of={[health, backups]} className="mb-3" />

        <div className="d-flex gap-2 mb-2 flex-wrap">
          <a href={backupDownloadUrl(true)} className="btn btn-primary" download>
            ↓ Full Backup
          </a>
          <a href={backupDownloadUrl(false)} className="btn btn-outline-primary" download>
            ↓ DB Only
          </a>
        </div>
        <p className="text-muted small mb-3" style={{ fontSize: '0.75rem' }}>
          <strong>Full</strong> = SQLite DB + every uploaded photo (hats and the site logo).
          Restore by dropping the extracted <code>data/</code> back into <code>/data/</code>.
          <br/>
          <strong>DB only</strong> = just <code>headroom.db</code>. All hat metadata, cases,
          colors, prices — but no photos. Faster to download.
        </p>
        {backups.data && backups.data.length > 0 && (
          <div>
            <div className="hr-tier-label mb-2">Scheduled snapshots ({backups.data.length})</div>
            {backups.data.map(b => (
              <div key={b.filename} className="hr-color-row" style={{ paddingTop: '0.5rem' }}>
                <div className="flex-grow-1 font-mono small" style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {b.filename}
                </div>
                <div className="text-muted small font-mono">{formatBytes(b.size_bytes)}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
