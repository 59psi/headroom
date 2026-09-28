import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ErrorNote } from '../common/ErrorNote';
import { listBackups, backupDownloadUrl, getBackupHealth } from '../../api/settings';
import type { BackupHealth, BackupInfo } from '../../types';
import { formatBytes, timeAgo } from '../../lib/format';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';

/**
 * Snapshots listed before "Show all". Retention is count-based, so the list
 * is as long as the keep setting — a dozen filenames that differ only in the
 * timestamp is a wall to scroll past on a phone, and the newest few are the
 * ones anybody restores from.
 */
const SNAPSHOTS_SHOWN = 5;

function absolute(iso: string | null | undefined): string | undefined {
  return iso ? new Date(iso).toLocaleString() : undefined;
}

/**
 * The scheduler's state in one word, for the card header.
 *
 * Ranked worst-first, the same order as the sentence in the body: a stopped
 * task outranks a failure count, because no further attempt is coming to
 * change it. Only ever derived from the health record — while that is still
 * loading (or failed to load) there is no pill at all, rather than a guess.
 */
function HealthPill({ h }: { h: BackupHealth }) {
  if (!h.enabled) {
    return <StatusPill tone="off" title="Scheduled backups are switched off for this deployment.">Off</StatusPill>;
  }
  if (!h.running) {
    return <StatusPill tone="error" title="The scheduler is not running.">Stopped</StatusPill>;
  }
  if (h.consecutive_failures > 0) {
    return (
      <StatusPill tone="error" title={`${h.consecutive_failures} in a row failed.`}>
        Failing
      </StatusPill>
    );
  }
  return <StatusPill tone="ok">Healthy</StatusPill>;
}

/**
 * Is the scheduler working — which the file list cannot answer.
 *
 * A scheduler that died three weeks ago and one that ran this morning produce
 * an identical inventory, and in both cases the newest file is the last
 * success. The endpoint that answers this has existed since 2.26 and nothing
 * rendered it, so the question stayed unanswerable outside curl.
 */
function SchedulerStatus({ h, files }: { h: BackupHealth; files: BackupInfo[] | undefined }) {
  // Ranked worst-first (see HealthPill).
  const problem = !h.enabled
    ? null
    : !h.running
      ? 'The scheduler is not running — no further backups will be written until restart.'
      : h.consecutive_failures > 0
        ? `${h.consecutive_failures} backup${h.consecutive_failures === 1 ? '' : 's'} in a row failed.`
        : null;
  const totalBytes = files?.reduce((sum, f) => sum + f.size_bytes, 0) ?? 0;
  // "Checked" is the proof of life for a change-gated scheduler: on an idle
  // collection the last SUCCESS stops advancing by design, and without the
  // last ATTEMPT beside it a healthy scheduler reads exactly like a dead one.
  const checkedSince = h.last_attempt_at && h.last_attempt_at !== h.last_success_at;

  return (
    <>
      {!h.enabled && (
        <p className="hr-upkeep-note">
          Scheduled backups are switched off for this deployment. On-demand
          downloads below still work.
        </p>
      )}
      {problem && <p className="hr-upkeep-alert">{problem}</p>}

      <div className="hr-metric-grid hr-upkeep-metrics">
        <div className="hr-metric">
          <div className="hr-metric-label">Last backup</div>
          <div className="hr-metric-value">
            <time dateTime={h.last_success_at ?? undefined} title={absolute(h.last_success_at)}>
              {timeAgo(h.last_success_at)}
            </time>
          </div>
          {/* Derived means a file exists, not that a run was recorded — the
              in-memory record is process-local and a restart clears it. */}
          {h.last_success_derived && (
            <div className="hr-upkeep-metric-sub">
              From the file on disk — this process has not run one yet
            </div>
          )}
          {checkedSince && (
            <div className="hr-upkeep-metric-sub">
              Checked{' '}
              <time dateTime={h.last_attempt_at ?? undefined} title={absolute(h.last_attempt_at)}>
                {timeAgo(h.last_attempt_at)}
              </time>
            </div>
          )}
        </div>
        {files && (
          <div className="hr-metric">
            <div className="hr-metric-label">Snapshots kept</div>
            <div className="hr-metric-value">{files.length}</div>
            {files.length > 0 && (
              <div className="hr-upkeep-metric-sub">{formatBytes(totalBytes)} on disk</div>
            )}
          </div>
        )}
      </div>

      {h.last_skip_reason && !problem && (
        <p className="hr-upkeep-note">
          {h.last_skip_reason} Backups are only written when something has
          changed, so an unchanged collection keeps the snapshot it already has
          rather than spending a slot restating it.
        </p>
      )}
      {h.last_error && <p className="hr-upkeep-error-text">{h.last_error}</p>}
    </>
  );
}

function SnapshotList({ files, scheduled }: { files: BackupInfo[]; scheduled: boolean }) {
  const [showAll, setShowAll] = useState(false);
  if (files.length === 0) {
    // Said only once the list has LOADED empty — a failed fetch renders its
    // ErrorNote instead, never "nothing here". The promise of a next one is
    // only made while the scheduler is on to keep it.
    return (
      <p className="hr-upkeep-note mb-0">
        No scheduled snapshots on disk yet
        {scheduled ? ' — one is written after the next change.' : '.'}
      </p>
    );
  }
  const shown = showAll ? files : files.slice(0, SNAPSHOTS_SHOWN);
  const hidden = files.length - shown.length;
  return (
    <div className="hr-upkeep-snapshots">
      <span className="hr-eyebrow">Scheduled snapshots</span>
      {/* Newest first — the server sorts, and retention counts from the top. */}
      <ul className="hr-upkeep-files" aria-label="Scheduled snapshots">
        {shown.map(b => (
          <li key={b.filename} className="hr-upkeep-file">
            <span className="hr-upkeep-file-name" title={b.filename}>{b.filename}</span>
            <span className="hr-upkeep-file-meta">
              <time dateTime={b.created_at} title={absolute(b.created_at)}>{timeAgo(b.created_at)}</time>
              {' · '}{formatBytes(b.size_bytes)}
            </span>
          </li>
        ))}
      </ul>
      {files.length > SNAPSHOTS_SHOWN && (
        <button
          type="button"
          className="btn btn-sm btn-outline-secondary hr-upkeep-more"
          aria-expanded={showAll}
          onClick={() => setShowAll(v => !v)}
        >
          {showAll ? 'Show fewer' : `Show all ${files.length} (${hidden} more)`}
        </button>
      )}
    </div>
  );
}

function DownloadIcon() {
  return (
    <svg className="hr-upkeep-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 4v11" /><path d="M7 10l5 5 5-5" /><path d="M5 20h14" />
    </svg>
  );
}

export function BackupsCard() {
  const toast = useToast();
  const backups = useQuery({ queryKey: ['admin', 'backups'], queryFn: listBackups });
  const health = useQuery({ queryKey: ['admin', 'backup-health'], queryFn: getBackupHealth });
  const loading = health.isPending || backups.isPending;

  // A download is a plain navigation the browser turns into a file, so the
  // page gets no completion event to acknowledge. The full archive is built
  // on the fly on a Pi and can take a moment to start; without a word here
  // the tap looks like it did nothing and gets tapped again.
  const started = () => toast.info('Preparing the download — your browser will save it shortly.');

  return (
    <Panel
      title="Backups"
      className="hr-upkeep-card"
      status={health.data && <HealthPill h={health.data} />}
      description="Automatic snapshots of your collection, plus a full download whenever you want one."
      help={
        <>
          <p>
            Backups are gzipped tarballs of <code>/data</code>. Scheduled rolling
            backups run inside the container and are kept under{' '}
            <code>/data/backups/</code>. They are only written when something
            has changed, so the snapshots span as much history as the collection
            took to change that many times.
          </p>
          <p>
            <strong>Full</strong> = SQLite DB + every uploaded photo (hats and
            the site logo). Restore by dropping the extracted <code>data/</code>{' '}
            back into <code>/data/</code>.
          </p>
          <p>
            <strong>Database only</strong> = just <code>headroom.db</code>. All
            hat metadata, cases, colors, prices — but no photos. Faster to
            download. Use it when the photo tree is large and you only need the
            metadata captured (photos are JPEG/PNG, so they barely compress
            anyway).
          </p>
        </>
      }
      footer={
        <>
          <a href={backupDownloadUrl(true)} className="btn btn-primary" download onClick={started}>
            <DownloadIcon /> Download full backup
          </a>
          <a href={backupDownloadUrl(false)} className="btn btn-outline-secondary" download onClick={started}>
            <DownloadIcon /> Database only
          </a>
          <p className="hr-upkeep-foot-note">
            Full includes every photo. Database only is all the metadata without
            photos — much smaller.
          </p>
        </>
      }
    >
      {loading ? (
        <Skeleton lines={3} />
      ) : (
        <>
          {health.data && <SchedulerStatus h={health.data} files={backups.data} />}
          <ErrorNote of={[health, backups]} className="mb-3" />
          {backups.data && (
            <SnapshotList
              files={backups.data}
              scheduled={!!health.data?.enabled && health.data.running}
            />
          )}
        </>
      )}
    </Panel>
  );
}
