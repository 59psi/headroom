import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  cancelImportJob,
  createImportJob,
  getImportJob,
  listImportJobs,
} from '../api/settings';
import { DEFAULT_HAT_BASICS, useHatFormOptions } from '../components/hats/HatFormFields';
import { OptionSelect } from '../components/hats/OptionSelect';
import { invalidateHatViews } from '../lib/invalidate';
import { formatBytes, plural } from '../lib/format';
import { qk } from '../lib/queryKeys';
import { ErrorNote } from '../components/common/ErrorNote';
import { PageHeader } from '../components/ui/PageHeader';
import { Panel } from '../components/ui/Panel';
import { StatusPill, type PillTone } from '../components/ui/StatusPill';
import { Skeleton } from '../components/ui/Skeleton';
import { useToast } from '../components/ui/Toast';
import { useConfirm } from '../components/ui/Dialogs';
import type { ImportJobItemRead, ImportJobRead } from '../types';

const MAX_FILES = 100;

/** What identifies a picked file — the row key, and the dedupe key. */
const fileKey = (f: File) => `${f.name}:${f.size}:${f.lastModified}`;

/** Same test the single-photo picker uses; see `PhotoCapture`. */
const isImage = (f: File) => f.type.startsWith('image/') || /\.(heic|heif)$/i.test(f.name);

/** A job's and an item's state as one word with a tone — never the tone alone. */
const JOB_PILL: Record<ImportJobRead['status'], { tone: PillTone; label: string }> = {
  queued: { tone: 'info', label: 'Queued' },
  running: { tone: 'busy', label: 'Running' },
  done: { tone: 'ok', label: 'Done' },
  canceled: { tone: 'off', label: 'Canceled' },
};

const ITEM_PILL: Record<ImportJobItemRead['status'], { tone: PillTone; label: string }> = {
  queued: { tone: 'off', label: 'Queued' },
  processing: { tone: 'busy', label: 'Processing' },
  done: { tone: 'ok', label: 'Done' },
  error: { tone: 'error', label: 'Error' },
  skipped: { tone: 'warn', label: 'Skipped' },
  canceled: { tone: 'off', label: 'Canceled' },
};

function pillFor<K extends string>(map: Record<K, { tone: PillTone; label: string }>, status: string) {
  // A status this build does not know still renders — as its own word.
  return map[status as K] ?? { tone: 'off' as PillTone, label: status };
}

export function BulkImportPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const fileInput = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  // ?job=N takes precedence so the Web Share Target redirect lands us
  // straight on the active job.
  const queryJobId = searchParams.get('job');
  const [activeJobId, setActiveJobId] = useState<number | null>(
    queryJobId ? Number(queryJobId) : null
  );

  // Keep state and URL in sync — clear ?job= when the user backs out.
  useEffect(() => {
    if (activeJobId == null && queryJobId) {
      setSearchParams({}, { replace: true });
    }
    if (activeJobId != null && !queryJobId) {
      setSearchParams({ job: String(activeJobId) }, { replace: true });
    }
  }, [activeJobId, queryJobId, setSearchParams]);

  // The option lists both hat forms use, with their one loading flag — this
  // page re-declared the style, size, condition and case queries by hand.
  const options = useHatFormOptions();
  const recentJobs = useQuery({ queryKey: qk.admin.importJobs(), queryFn: () => listImportJobs(10) });

  const [defaultCondition, setDefaultCondition] = useState(DEFAULT_HAT_BASICS.condition);
  const [defaultSize, setDefaultSize] = useState(DEFAULT_HAT_BASICS.size);
  const [defaultStyle, setDefaultStyle] = useState(DEFAULT_HAT_BASICS.style);
  const [defaultCaseId, setDefaultCaseId] = useState('');

  // Live while the job is: the progress bar, the counts and every row's pill
  // update on their own every 2s, and the polling stops the moment the job
  // reaches a terminal state.
  const job = useQuery({
    queryKey: qk.admin.importJob(activeJobId),
    queryFn: () => getImportJob(activeJobId!),
    enabled: activeJobId != null,
    refetchInterval: (q) => {
      // Stop on error, or a bad ?job= id polls a 404 every 2s forever.
      if (q.state.status === 'error') return false;
      const data = q.state.data;
      if (!data) return 2000;
      return data.status === 'running' || data.status === 'queued' ? 2000 : false;
    },
  });

  const submit = useMutation({
    mutationFn: () => createImportJob(files, {
      case_id: defaultCaseId ? Number(defaultCaseId) : null,
      condition: defaultCondition,
      size: defaultSize,
      style: defaultStyle,
    }),
    onSuccess: (data) => {
      setFiles([]);
      setActiveJobId(data.id);
      qc.invalidateQueries({ queryKey: qk.admin.importJobs() });
      toast.success(`Import started — ${plural(data.total, 'photo')} queued`);
    },
  });

  const cancelMut = useMutation({
    mutationFn: (id: number) => cancelImportJob(id),
    onSuccess: (data) => {
      // The DELETE answers with the job as it now stands; show it at once
      // rather than waiting for the next poll, which is about to stop anyway.
      if (data && data.id === activeJobId) qc.setQueryData(qk.admin.importJob(activeJobId), data);
      qc.invalidateQueries({ queryKey: qk.admin.importJob(activeJobId) });
      qc.invalidateQueries({ queryKey: qk.admin.importJobs() });
      toast.success('Import canceled');
    },
  });

  // When a job finishes, refresh everything a new hat is visible in. Bulk
  // import creates hats INTO a case, so `['case']` (that case's own hat list)
  // and `['rooms']` (per-room counts) go stale too — this used to invalidate
  // only `['hats']` and `['cases']`, which left the case you had just filled
  // showing its old contents for the 30s staleTime. Highest-volume path in the
  // app, so the worst place to hand-roll the subset.
  //
  // The "finished" toast only fires on a transition this page WATCHED — the
  // same job going from running to done — so opening an old finished job from
  // Recent imports does not announce it as news.
  const seen = useRef<{ id: number | null; status?: string }>({ id: null });
  // The counts are read at the moment the status flips; the effect is about
  // the flip, not about every poll, so they come through a ref.
  const latestJob = useRef(job.data);
  latestJob.current = job.data;
  const status = job.data?.status;
  const jobId = job.data?.id ?? null;
  useEffect(() => {
    const prev = seen.current;
    seen.current = { id: jobId, status };
    if (status !== 'done') return;
    invalidateHatViews(qc);
    const finished = latestJob.current;
    if (prev.id === jobId && (prev.status === 'running' || prev.status === 'queued') && finished) {
      toast.success(`Import finished — ${finished.done} of ${finished.total} added`);
    }
  }, [status, jobId, qc, toast]);

  function addFiles(picked: File[]) {
    // Keyed on what identifies a file rather than its position: removing row
    // 3 of 10 with index keys re-labels every row beneath it. The same key
    // also dedupes a file picked twice.
    setFiles(prev => {
      const seenKeys = new Set(prev.map(fileKey));
      const fresh = picked.filter(f => !seenKeys.has(fileKey(f)) && seenKeys.add(fileKey(f)));
      return [...prev, ...fresh].slice(0, MAX_FILES);
    });
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    addFiles(Array.from(e.target.files ?? []));
    e.target.value = ''; // allow re-picking same files
  }

  function removeFile(key: string) {
    setFiles(prev => prev.filter(f => fileKey(f) !== key));
  }

  // One tap empties a list that may be a hundred photos long, and the button
  // sits right beside "Add more" at the same weight — so it can be taken
  // back. The cleared list returns in its old order, with anything added
  // since kept after it (deduped the same way).
  function clearFiles() {
    const cleared = files;
    setFiles([]);
    toast.info(`${plural(cleared.length, 'photo')} cleared`, {
      action: {
        label: 'Undo',
        onClick: () => setFiles(prev => {
          const restored = new Set(cleared.map(fileKey));
          return [...cleared, ...prev.filter(f => !restored.has(fileKey(f)))].slice(0, MAX_FILES);
        }),
      },
    });
  }

  async function confirmCancel(id: number) {
    const ok = await confirm({
      title: 'Cancel this import?',
      body: 'Photos still waiting are dropped. The one being processed finishes, and hats already imported stay.',
      confirmLabel: 'Cancel import',
      cancelLabel: 'Keep going',
      tone: 'danger',
    });
    if (ok) cancelMut.mutate(id);
  }

  // Drag-and-drop a folder's worth of photos from Finder or Files onto the
  // Photos card — the same list the picker fills, deduped the same way.
  const dropHandlers = {
    onDragOver: (e: React.DragEvent) => {
      if (!Array.from(e.dataTransfer?.types ?? []).includes('Files')) return;
      e.preventDefault();
      setDragging(true);
    },
    onDragLeave: (e: React.DragEvent) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
    },
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      addFiles(Array.from(e.dataTransfer.files).filter(isImage));
    },
  };

  const jobData = activeJobId != null ? job.data : undefined;
  const processed = jobData ? jobData.done + jobData.errors + jobData.skipped : 0;
  const pct = jobData ? Math.round((processed / Math.max(1, jobData.total)) * 100) : 0;

  return (
    <>
      <PageHeader
        title="Bulk import"
        actions={<Link to="/hats" className="btn btn-outline-secondary btn-sm">← Hats</Link>}
      />

      {/* The option lists feed the defaults form below; a failed fetch used
          to render three empty selects with no explanation. */}
      <ErrorNote
        of={[options.styles, options.sizes, options.conditions, options.cases, recentJobs]}
        what="Could not load the import options"
        className="mb-3"
      />

      {activeJobId != null && job.error && (
        // "Error", not "Not found": the fetch can fail for reasons other than
        // a removed job, and the pill states only what is known.
        <Panel title={`Import #${activeJobId}`} status={<StatusPill tone="error">Error</StatusPill>}>
          <div className="alert alert-danger">
            Couldn't load import job #{activeJobId}. It may have been removed.
          </div>
          <button
            type="button"
            className="btn btn-primary w-100"
            onClick={() => { setActiveJobId(null); navigate('/hats/import'); }}
          >Start a new import</button>
        </Panel>
      )}

      {activeJobId != null && job.isLoading && (
        <Panel title={`Import #${activeJobId}`}>
          <Skeleton lines={4} />
        </Panel>
      )}

      {!activeJobId && (
        <>
          <Panel
            title="Defaults for every hat"
            description="You can edit each hat after Claude finishes analyzing it."
          >
            {options.isLoading ? <Skeleton lines={2} /> : (
              <div className="hr-import-defaults">
                <OptionSelect id="import-style" label="Style" value={defaultStyle} onChange={setDefaultStyle} options={options.styles.data} />
                <OptionSelect id="import-size" label="Size" value={defaultSize} onChange={setDefaultSize} options={options.sizes.data} />
                <OptionSelect id="import-condition" label="Condition" value={defaultCondition} onChange={setDefaultCondition} options={options.conditions.data} />
                <div>
                  <label className="form-label" htmlFor="import-case">Case</label>
                  <select id="import-case" className="form-select" value={defaultCaseId} onChange={e => setDefaultCaseId(e.target.value)}>
                    <option value="">Unassigned</option>
                    {/* "A-001 (1 hat)", never "(1 hats)". */}
                    {options.cases.data?.map(c => (
                      <option key={c.id} value={c.id}>{c.display_id} ({plural(c.hat_count, 'hat')})</option>
                    ))}
                  </select>
                </div>
              </div>
            )}
          </Panel>

          <div className={`hr-import-drop-zone${dragging ? ' is-dragging' : ''}`} {...dropHandlers}>
            <Panel
              title="Photos"
              status={(
                <StatusPill tone={files.length ? 'info' : 'off'}>
                  {files.length} of {MAX_FILES}
                </StatusPill>
              )}
              actions={files.length > 0 && (
                <>
                  <button
                    type="button"
                    className="btn btn-outline-secondary btn-sm"
                    onClick={clearFiles}
                  >
                    Clear
                  </button>
                  <button
                    type="button"
                    className="btn btn-outline-secondary btn-sm"
                    onClick={() => fileInput.current?.click()}
                    disabled={files.length >= MAX_FILES}
                  >
                    + Add more
                  </button>
                </>
              )}
              help={(
                <p>
                  Each photo goes through the same pipeline as a single upload
                  (resize → background removal → Claude analysis), one at a time,
                  in the background — you can leave this page once it starts.
                </p>
              )}
              footer={(
                <button
                  type="button"
                  className="btn btn-primary hr-import-start"
                  disabled={files.length === 0 || submit.isPending}
                  onClick={() => submit.mutate()}
                >
                  {submit.isPending ? 'Queuing…' : `Start import (${files.length})`}
                </button>
              )}
            >
              <input
                ref={fileInput}
                type="file"
                accept="image/*"
                multiple
                hidden
                aria-label="Choose photos to import"
                onChange={handleFileSelect}
              />
              {files.length === 0 ? (
                // The empty list IS the picker: one big target instead of a
                // sentence and a small button in the corner.
                <button type="button" className="hr-photo-drop hr-import-empty" onClick={() => fileInput.current?.click()}>
                  <span className="hr-photo-drop-title">Add photos</span>
                  <span className="hr-photo-drop-hint">
                    Pick up to {MAX_FILES} at once
                    <span className="hr-drop-hint-fine"> — or drop them here</span>
                  </span>
                </button>
              ) : (
                <ol className="hr-import-list">
                  {files.map((f, idx) => (
                    <li key={fileKey(f)} className="hr-import-row">
                      <span className="hr-import-index">{idx + 1}.</span>
                      <div className="hr-import-file">
                        <div className="hr-import-name">{f.name}</div>
                        <div className="hr-import-meta">{formatBytes(f.size)}</div>
                      </div>
                      <button
                        type="button"
                        className="btn btn-outline-secondary btn-sm hr-import-remove"
                        aria-label={`Remove ${f.name}`}
                        onClick={() => removeFile(fileKey(f))}
                      >×</button>
                    </li>
                  ))}
                </ol>
              )}
              <ErrorNote of={submit} className="mt-3 mb-0" />
            </Panel>
          </div>
        </>
      )}

      {jobData && (
        <Panel
          title={`Import #${jobData.id}`}
          status={(() => {
            const p = pillFor(JOB_PILL, jobData.status);
            return <StatusPill tone={p.tone}>{p.label}</StatusPill>;
          })()}
          actions={(jobData.status === 'queued' || jobData.status === 'running') && (
            <button
              type="button"
              className="btn btn-outline-danger btn-sm"
              onClick={() => { void confirmCancel(jobData.id); }}
              disabled={cancelMut.isPending}
            >{cancelMut.isPending ? 'Canceling…' : 'Cancel'}</button>
          )}
          footer={(jobData.status === 'done' || jobData.status === 'canceled') && (
            <>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => { setActiveJobId(null); navigate('/hats'); }}
              >{jobData.status === 'done' ? 'Done — go to hats' : 'Canceled — go to hats'}</button>
              <button
                type="button"
                className="btn btn-outline-secondary"
                onClick={() => setActiveJobId(null)}
              >Start another import</button>
            </>
          )}
        >
          <ErrorNote of={cancelMut} what="Could not cancel" className="mb-3" />
          <div
            className="hr-progress hr-import-progress"
            role="progressbar"
            aria-label="Import progress"
            aria-valuemin={0}
            aria-valuemax={jobData.total}
            aria-valuenow={processed}
          >
            <div className="hr-progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <div className="hr-metric-grid hr-import-counts">
            <div className="hr-metric">
              <div className="hr-metric-label">Done</div>
              <div className="hr-metric-value">{jobData.done}</div>
            </div>
            <div className="hr-metric">
              <div className="hr-metric-label">Errors</div>
              <div className="hr-metric-value">{jobData.errors}</div>
            </div>
            <div className="hr-metric">
              <div className="hr-metric-label">Skipped</div>
              <div className="hr-metric-value">{jobData.skipped}</div>
            </div>
            <div className="hr-metric">
              <div className="hr-metric-label">Of</div>
              <div className="hr-metric-value">{jobData.total}</div>
            </div>
          </div>
          <ol className="hr-import-list">
            {jobData.items.map(item => {
              const p = pillFor(ITEM_PILL, item.status);
              return (
                <li key={item.id} className="hr-import-row">
                  <div className="hr-import-file">
                    <div className="hr-import-name">{item.filename}</div>
                    {item.error && <div className="hr-import-error">{item.error}</div>}
                  </div>
                  <div className="hr-import-item-state">
                    <StatusPill tone={p.tone}>{p.label}</StatusPill>
                    {item.hat_id && (
                      <Link to={`/hats/${item.hat_id}`} className="hr-import-view">View hat →</Link>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        </Panel>
      )}

      {!activeJobId && (recentJobs.data?.length ?? 0) > 0 && (
        <Panel title="Recent imports">
          <ul className="hr-import-list">
            {recentJobs.data?.map(j => {
              const p = pillFor(JOB_PILL, j.status);
              return (
                <li key={j.id}>
                  <button
                    type="button"
                    className="hr-import-row hr-import-job"
                    onClick={() => setActiveJobId(j.id)}
                  >
                    <span className="hr-import-file">
                      <span className="hr-import-name font-mono">Import #{j.id}</span>
                      <span className="hr-import-meta">
                        {j.created_at ? new Date(j.created_at).toLocaleString() : '—'}
                      </span>
                    </span>
                    <span className="hr-import-item-state">
                      <StatusPill tone={p.tone}>{p.label}</StatusPill>
                      <span className="hr-import-meta font-mono">{j.done}/{j.total}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </Panel>
      )}
    </>
  );
}
