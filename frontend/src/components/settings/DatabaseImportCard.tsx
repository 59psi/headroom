import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  applyImport, discardImport, getStagedImport, listRestorePoints, stageImportUpload, stageRestorePoint,
} from '../../api/settings';
import type { DatabaseImportPreview, RestorePointRead } from '../../types';
import { formatBytes, plural, timeAgo } from '../../lib/format';
import { invalidateEverything } from '../../lib/invalidate';
import { qk } from '../../lib/queryKeys';
import { ErrorNote } from '../common/ErrorNote';
import { useConfirm } from '../ui/Dialogs';
import { Panel } from '../ui/Panel';
import { Skeleton } from '../ui/Skeleton';
import { StatusPill } from '../ui/StatusPill';
import { useToast } from '../ui/Toast';

/** Listed before "Show all": the newest few are the ones anybody restores. */
const POINTS_SHOWN = 4;

function absolute(iso: string | null | undefined): string | undefined {
  return iso ? new Date(iso).toLocaleString() : undefined;
}

/** What a file in `backups/` is, in words — its name says why it exists. */
function describePoint(p: RestorePointRead): string {
  if (p.kind === 'archive') return 'Full backup';
  if (p.name.startsWith('pre-import-')) return 'Saved before an import';
  if (p.name.startsWith('pre-upgrade-')) return 'Saved before an upgrade';
  return 'Database copy';
}

function PointList({
  points, busy, onUse,
}: {
  points: RestorePointRead[];
  busy: boolean;
  onUse: (name: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  if (points.length === 0) {
    return <p className="hr-upkeep-note">No backups on this server yet.</p>;
  }
  const shown = showAll ? points : points.slice(0, POINTS_SHOWN);
  return (
    <div className="hr-upkeep-snapshots">
      <span className="hr-eyebrow">On this server</span>
      {/* Newest first, as the server sorts them. */}
      <ul className="hr-upkeep-files" aria-label="Backups on this server">
        {shown.map(p => (
          <li key={p.name} className="hr-upkeep-file hr-import-point">
            <span className="hr-import-point-text">
              <span className="hr-upkeep-file-name" title={p.name}>{p.name}</span>
              <span className="hr-upkeep-file-meta">
                {describePoint(p)}{' · '}
                <time dateTime={p.created_at} title={absolute(p.created_at)}>{timeAgo(p.created_at)}</time>
                {' · '}{formatBytes(p.size_bytes)}
              </span>
            </span>
            <button
              type="button"
              className="btn btn-sm btn-outline-secondary"
              aria-label={`Use ${p.name}`}
              disabled={busy}
              onClick={() => onUse(p.name)}
            >
              Use
            </button>
          </li>
        ))}
      </ul>
      {points.length > POINTS_SHOWN && (
        <button
          type="button"
          className="btn btn-sm btn-outline-secondary hr-upkeep-more"
          aria-expanded={showAll}
          onClick={() => setShowAll(v => !v)}
        >
          {showAll ? 'Show fewer' : `Show all ${points.length}`}
        </button>
      )}
    </div>
  );
}

/** What the staged file holds, and what it would replace — read before anything changes. */
function Preview({ p }: { p: DatabaseImportPreview }) {
  return (
    <section className="hr-import-preview" aria-label="What this file holds">
      <span className="hr-eyebrow">Ready to import</span>
      <p className="hr-import-source">{p.source}</p>
      <p className="hr-upkeep-note">
        {p.kind === 'archive' ? 'A full backup' : 'A database file'}
        {p.version ? `, last run by Headroom ${p.version}` : ''}
        {p.newest_change_at ? (
          <>
            {'. Newest change '}
            <time dateTime={p.newest_change_at} title={absolute(p.newest_change_at)}>
              {timeAgo(p.newest_change_at)}
            </time>
          </>
        ) : null}
        .
      </p>
      <div className="hr-metric-grid hr-upkeep-metrics">
        <div className="hr-metric">
          <div className="hr-metric-label">Hats</div>
          <div className="hr-metric-value">{p.hats}</div>
          {p.disposed_hats > 0 && (
            <div className="hr-upkeep-metric-sub">and {p.disposed_hats} disposed</div>
          )}
        </div>
        <div className="hr-metric">
          <div className="hr-metric-label">Cases</div>
          <div className="hr-metric-value">{p.cases}</div>
          <div className="hr-upkeep-metric-sub">in {plural(p.rooms, 'room')}</div>
        </div>
        <div className="hr-metric">
          <div className="hr-metric-label">Purchases</div>
          <div className="hr-metric-value">{p.purchases}</div>
          <div className="hr-upkeep-metric-sub">{plural(p.wear_logs, 'wear')} logged</div>
        </div>
        {p.kind === 'archive' && (
          <div className="hr-metric">
            <div className="hr-metric-label">Photos</div>
            <div className="hr-metric-value">{p.photos_included}</div>
          </div>
        )}
      </div>
      {p.photos_missing > 0 && (
        <p className="hr-upkeep-alert is-warn">
          {plural(p.photos_missing, 'hat')} would show no photo: {p.photos_missing === 1 ? 'its picture is' : 'their pictures are'}{' '}
          in neither this file nor this server.
          {p.kind === 'database' && ' A full backup (.tar.gz) carries the photos.'}
        </p>
      )}
      {p.degraded && (
        <p className="hr-upkeep-alert is-warn">
          This backup was written by the fallback copy and could have been
          caught mid-write. It passed SQLite&rsquo;s integrity check; look over
          the collection afterwards.
        </p>
      )}
      <p className="hr-upkeep-note mb-0">
        {p.current_hats > 0
          ? `It replaces the ${plural(p.current_hats, 'hat')} here. `
          : 'There are no hats here yet to replace. '}
        {p.keeps_account && 'Your sign-in, passkeys, share links and settings stay as they are. '}
        The current collection is saved first, so this can be undone.
      </p>
    </section>
  );
}

function ImportIcon() {
  return (
    <svg className="hr-upkeep-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 15V4" /><path d="M7 9l5-5 5 5" /><path d="M5 20h14" />
    </svg>
  );
}

export function DatabaseImportCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const inputRef = useRef<HTMLInputElement>(null);
  const points = useQuery({ queryKey: qk.admin.restorePoints(), queryFn: listRestorePoints });
  // A staged import survives a reload on the server, so the card asks for it:
  // the preview comes back instead of a second upload of the same archive.
  const staged = useQuery({ queryKey: qk.admin.stagedImport(), queryFn: getStagedImport });

  const stage = useMutation({
    mutationFn: (source: { file: File } | { name: string }) =>
      'file' in source ? stageImportUpload(source.file) : stageRestorePoint(source.name),
    onSuccess: preview => qc.setQueryData(qk.admin.stagedImport(), preview),
  });
  const discard = useMutation({
    mutationFn: (token: string) => discardImport(token),
    onSettled: () => qc.setQueryData(qk.admin.stagedImport(), null),
  });
  const apply = useMutation({
    mutationFn: (token: string) => applyImport(token),
    onSuccess: result => {
      qc.setQueryData(qk.admin.stagedImport(), null);
      toast.success(
        `Imported ${plural(result.hats, 'hat')}. The collection it replaced is saved as ${result.snapshot}.`,
      );
      // Every list, count and detail in the cache is about a collection that
      // is gone — this card's own restore points included (the copy is new).
      void invalidateEverything(qc);
    },
  });

  const preview = staged.data ?? null;
  const busy = stage.isPending || apply.isPending || discard.isPending;

  function begin(source: { file: File } | { name: string }) {
    // The ErrorNote shows the FIRST failure in its list: a refusal from an
    // earlier attempt must not stand in for this one's answer.
    for (const m of [stage, apply, discard]) if (m.isError) m.reset();
    stage.mutate(source);
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    // Cleared so picking the same file again (after a refusal) fires `change`.
    e.target.value = '';
    if (file) begin({ file });
  }

  async function replace(p: DatabaseImportPreview) {
    const ok = await confirm({
      title: 'Replace your collection?',
      body: (p.current_hats > 0
        ? `The ${plural(p.current_hats, 'hat')} here become the ${plural(p.hats, 'hat')} in ${p.source}. `
        : `This collection becomes the ${plural(p.hats, 'hat')} in ${p.source}. `)
        + 'The current collection is saved first, as a copy you can import to undo this.',
      confirmLabel: 'Replace collection',
      tone: 'danger',
    });
    if (ok) apply.mutate(p.token);
  }

  const status = apply.isPending
    ? <StatusPill tone="busy">Importing</StatusPill>
    : stage.isPending
      ? <StatusPill tone="busy">Reading</StatusPill>
      : preview
        ? <StatusPill tone="info" title="A file is waiting to be confirmed.">Review</StatusPill>
        : <StatusPill tone="off">Idle</StatusPill>;

  return (
    <Panel
      title="Import a database"
      className="hr-upkeep-card"
      status={status}
      description="Replace this collection with a backup: one saved on this server, or a file from this device."
      help={
        <>
          <p>
            Takes a Headroom backup — a full archive (<code>.tar.gz</code>:
            the database and its photos) or a database file
            (<code>.db</code>) — and puts its collection in place of this
            one. A backup from an older version is brought up to date on the
            way in; one from a newer Headroom is refused until this server is
            upgraded.
          </p>
          <p>
            <strong>What changes:</strong> hats, cases, rooms, colors, wears,
            purchases and their history become the file&rsquo;s.{' '}
            <strong>What stays:</strong> your sign-in and password, passkeys,
            share links, guest browsing, API keys, model and off-site backup,
            exactly as they are. Hat and case numbers never go backwards, so
            printed tags keep pointing where they did.
          </p>
          <p>
            <strong>Undo:</strong> before anything is replaced, the current
            database is saved as <code>pre-import-&lt;time&gt;.db</code>. It
            appears in the list here, and importing it puts everything back.
            Photos are only ever added — never deleted or replaced — so the
            undo has all its pictures.
          </p>
          <p className="mb-0">
            It waits while photos are being analyzed or imported. For a file
            too big to send from this device, run{' '}
            <code>./scripts/import-database.sh FILE</code> on the server
            (OPERATIONS §4).
          </p>
        </>
      }
      footer={preview ? (
        <>
          <button
            type="button"
            className="btn btn-danger"
            disabled={busy}
            onClick={() => replace(preview)}
          >
            {apply.isPending ? 'Importing…' : 'Replace my collection'}
          </button>
          <button
            type="button"
            className="btn btn-outline-secondary"
            disabled={busy}
            onClick={() => discard.mutate(preview.token)}
          >
            Cancel
          </button>
        </>
      ) : (
        <>
          <button
            type="button"
            className="btn btn-outline-secondary"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
          >
            <ImportIcon /> {stage.isPending ? 'Reading the file…' : 'Choose a file…'}
          </button>
          <p className="hr-upkeep-foot-note">
            A .tar.gz backup or a .db file. Nothing changes until you confirm.
          </p>
        </>
      )}
    >
      {points.isPending || staged.isPending ? (
        <Skeleton lines={3} />
      ) : preview ? (
        <Preview p={preview} />
      ) : points.data ? (
        <PointList points={points.data} busy={busy} onUse={name => begin({ name })} />
      ) : null}

      {/* No `accept`: iOS greys out a .db it has no type for, and the server
          says plainly what it will take. */}
      <input ref={inputRef} type="file" onChange={handleFileChange} hidden />

      <ErrorNote of={[stage, apply, discard, points, staged]} className="mt-3" />
    </Panel>
  );
}
