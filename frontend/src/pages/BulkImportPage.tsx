import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  cancelImportJob,
  createImportJob,
  getImportJob,
  listImportJobs,
} from '../api/settings';
import { getStyles, getSizes, getConditions } from '../api/hats';
import { listCases } from '../api/cases';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

const MAX_FILES = 100;

function shortBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

export function BulkImportPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);

  const styles = useQuery({ queryKey: ['meta', 'styles'], queryFn: getStyles });
  const sizes = useQuery({ queryKey: ['meta', 'sizes'], queryFn: getSizes });
  const conditions = useQuery({ queryKey: ['meta', 'conditions'], queryFn: getConditions });
  const cases = useQuery({ queryKey: ['cases'], queryFn: listCases });
  const recentJobs = useQuery({ queryKey: ['admin', 'import-jobs'], queryFn: () => listImportJobs(10) });

  const [defaultCondition, setDefaultCondition] = useState('new');
  const [defaultSize, setDefaultSize] = useState('classic');
  const [defaultStyle, setDefaultStyle] = useState('a_game');
  const [defaultCaseId, setDefaultCaseId] = useState('');

  const job = useQuery({
    queryKey: ['admin', 'import-job', activeJobId],
    queryFn: () => getImportJob(activeJobId!),
    enabled: activeJobId != null,
    refetchInterval: (q) => {
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
      qc.invalidateQueries({ queryKey: ['admin', 'import-jobs'] });
    },
  });

  const cancelMut = useMutation({
    mutationFn: (id: number) => cancelImportJob(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'import-job', activeJobId] });
      qc.invalidateQueries({ queryKey: ['admin', 'import-jobs'] });
    },
  });

  // When a job finishes, refresh the hats list so it shows up everywhere
  useEffect(() => {
    if (job.data?.status === 'done') {
      qc.invalidateQueries({ queryKey: ['hats'] });
      qc.invalidateQueries({ queryKey: ['cases'] });
    }
  }, [job.data?.status, qc]);

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? []);
    setFiles(prev => [...prev, ...picked].slice(0, MAX_FILES));
    e.target.value = ''; // allow re-picking same files
  }

  function removeFile(idx: number) {
    setFiles(prev => prev.filter((_, i) => i !== idx));
  }

  if (styles.isLoading || sizes.isLoading || conditions.isLoading) {
    return <LoadingSpinner />;
  }

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3 gap-2 flex-wrap">
        <h1>Bulk Import</h1>
        <Link to="/hats" className="btn btn-outline-secondary btn-sm">← Hats</Link>
      </div>

      {!activeJobId && (
        <>
          <div className="card mb-3">
            <div className="card-body">
              <div className="card-title">Defaults applied to every hat</div>
              <p className="text-secondary small mb-3">
                You can edit each hat after Claude finishes analysing it.
              </p>
              <div className="row g-2">
                <div className="col-6 col-md-3">
                  <label className="form-label">Style</label>
                  <select className="form-select" value={defaultStyle} onChange={e => setDefaultStyle(e.target.value)}>
                    {styles.data?.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                  </select>
                </div>
                <div className="col-6 col-md-3">
                  <label className="form-label">Size</label>
                  <select className="form-select" value={defaultSize} onChange={e => setDefaultSize(e.target.value)}>
                    {sizes.data?.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                  </select>
                </div>
                <div className="col-6 col-md-3">
                  <label className="form-label">Condition</label>
                  <select className="form-select" value={defaultCondition} onChange={e => setDefaultCondition(e.target.value)}>
                    {conditions.data?.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                  </select>
                </div>
                <div className="col-6 col-md-3">
                  <label className="form-label">Case</label>
                  <select className="form-select" value={defaultCaseId} onChange={e => setDefaultCaseId(e.target.value)}>
                    <option value="">Unassigned</option>
                    {cases.data?.map(c => (
                      <option key={c.id} value={c.id}>{c.display_id} ({c.hat_count} hats)</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>
          </div>

          <div className="card mb-3">
            <div className="card-body">
              <div className="d-flex justify-content-between align-items-center mb-2">
                <div className="card-title mb-0">Photos ({files.length} / {MAX_FILES})</div>
                <button
                  type="button"
                  className="btn btn-outline-primary btn-sm"
                  onClick={() => fileInput.current?.click()}
                  disabled={files.length >= MAX_FILES}
                >
                  + Add Photos
                </button>
                <input
                  ref={fileInput}
                  type="file"
                  accept="image/*"
                  multiple
                  hidden
                  onChange={handleFileSelect}
                />
              </div>
              {files.length === 0 ? (
                <p className="text-muted small mb-0">
                  Pick up to {MAX_FILES} photos. Each goes through the same pipeline as a single
                  upload (resize → background removal → Claude analysis), one at a time, in the
                  background.
                </p>
              ) : (
                <div>
                  {files.map((f, idx) => (
                    <div key={idx} className="hr-color-row" style={{ paddingTop: '0.5rem' }}>
                      <div className="font-mono small text-muted" style={{ minWidth: 28 }}>{idx + 1}.</div>
                      <div className="flex-grow-1" style={{ minWidth: 0 }}>
                        <div className="small" style={{
                          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                        }}>{f.name}</div>
                        <div className="text-muted small font-mono" style={{ fontSize: '0.7rem' }}>
                          {shortBytes(f.size)}
                        </div>
                      </div>
                      <button
                        type="button"
                        className="btn btn-outline-danger btn-sm"
                        onClick={() => removeFile(idx)}
                      >×</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {submit.error && (
            <div className="alert alert-danger">{String(submit.error)}</div>
          )}

          <button
            type="button"
            className="btn btn-primary w-100 btn-lg"
            disabled={files.length === 0 || submit.isPending}
            onClick={() => submit.mutate()}
          >
            {submit.isPending ? 'Queuing…' : `Start Import (${files.length})`}
          </button>
        </>
      )}

      {activeJobId && job.data && (
        <div className="card mb-3">
          <div className="card-body">
            <div className="d-flex justify-content-between align-items-center mb-2">
              <div className="card-title mb-0">Job #{job.data.id} · {job.data.status}</div>
              {(job.data.status === 'queued' || job.data.status === 'running') && (
                <button
                  type="button"
                  className="btn btn-outline-danger btn-sm"
                  onClick={() => cancelMut.mutate(job.data!.id)}
                  disabled={cancelMut.isPending}
                >Cancel</button>
              )}
            </div>
            <div className="text-secondary small mb-3">
              {job.data.done} done · {job.data.errors} errors · {job.data.skipped} skipped · of {job.data.total}
            </div>
            <div style={{
              height: 8, background: 'rgba(0,0,0,0.3)', borderRadius: 4, overflow: 'hidden',
              marginBottom: '1rem',
            }}>
              <div style={{
                height: '100%',
                width: `${Math.round(((job.data.done + job.data.errors + job.data.skipped) / Math.max(1, job.data.total)) * 100)}%`,
                background: 'var(--gradient-pink-cyan)',
                transition: 'width 0.3s ease',
              }} />
            </div>
            {job.data.items.map(item => (
              <div key={item.id} className="hr-color-row" style={{ paddingTop: '0.5rem' }}>
                <div className="flex-grow-1" style={{ minWidth: 0 }}>
                  <div className="small" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {item.filename}
                  </div>
                  {item.error && (
                    <div className="text-danger small font-mono" style={{ fontSize: '0.7rem' }}>{item.error}</div>
                  )}
                </div>
                <div className="text-end">
                  <div className={
                    item.status === 'done' ? 'badge bg-info' :
                    item.status === 'error' ? 'badge bg-warning' :
                    item.status === 'cancelled' ? 'badge bg-secondary' :
                    'badge bg-light'
                  }>{item.status}</div>
                  {item.hat_id && (
                    <div className="small mt-1">
                      <a href={`/hats/${item.hat_id}`} onClick={(e) => { e.preventDefault(); navigate(`/hats/${item.hat_id}`); }}>
                        view hat →
                      </a>
                    </div>
                  )}
                </div>
              </div>
            ))}
            {job.data.status === 'done' && (
              <button
                type="button"
                className="btn btn-primary w-100 mt-3"
                onClick={() => { setActiveJobId(null); navigate('/hats'); }}
              >Done — go to Hats</button>
            )}
          </div>
        </div>
      )}

      {!activeJobId && (recentJobs.data?.length ?? 0) > 0 && (
        <div className="card mb-3">
          <div className="card-body">
            <div className="card-title">Recent Imports</div>
            {recentJobs.data?.map(j => (
              <button
                key={j.id}
                type="button"
                className="hr-color-row text-decoration-none"
                style={{ paddingTop: '0.5rem', background: 'transparent', border: 0, width: '100%' }}
                onClick={() => setActiveJobId(j.id)}
              >
                <div className="flex-grow-1 text-start">
                  <div className="font-mono small">Job #{j.id}</div>
                  <div className="text-muted small">{new Date(j.created_at).toLocaleString()}</div>
                </div>
                <div className="text-end">
                  <div className="badge bg-info">{j.status}</div>
                  <div className="text-muted small font-mono">{j.done}/{j.total}</div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
