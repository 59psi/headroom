import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getLogo, uploadLogo, deleteLogo,
  getApiKeyStatus, setApiKey, deleteApiKey, testApiKey,
  getModel, setModel, clearModel,
  getRecentErrors, listBackups, backupDownloadUrl,
} from '../api/settings';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

// Curated list of Claude models known to support vision + tool use.
// "Other…" reveals a free-text input for anything not in the list.
const KNOWN_MODELS: { id: string; label: string }[] = [
  { id: 'claude-sonnet-4-6', label: 'Sonnet 4.6 — balanced (default)' },
  { id: 'claude-sonnet-4-5', label: 'Sonnet 4.5 — older, cheaper' },
  { id: 'claude-opus-4-7', label: 'Opus 4.7 — most capable, pricier' },
  { id: 'claude-haiku-4-5-20251001', label: 'Haiku 4.5 — fastest, cheapest' },
];
const OTHER = '__other__';

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export function SettingsPage() {
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [keyDraft, setKeyDraft] = useState('');
  const [modelDraft, setModelDraft] = useState('');
  const [modelSelect, setModelSelect] = useState<string>('');
  const [testResult, setTestResult] = useState<{ ok: boolean; detail: string } | null>(null);

  const logo = useQuery({ queryKey: ['settings', 'logo'], queryFn: getLogo });
  const apiKey = useQuery({ queryKey: ['settings', 'api-key'], queryFn: getApiKeyStatus });
  const model = useQuery({ queryKey: ['settings', 'model'], queryFn: getModel });
  const errors = useQuery({ queryKey: ['admin', 'recent-errors'], queryFn: () => getRecentErrors(20) });
  const backups = useQuery({ queryKey: ['admin', 'backups'], queryFn: listBackups });

  useEffect(() => {
    if (!model.data?.model_id) return;
    const id = model.data.model_id;
    if (!modelDraft) setModelDraft(id);
    if (!modelSelect) {
      const matches = KNOWN_MODELS.some(m => m.id === id);
      setModelSelect(matches ? id : OTHER);
    }
  }, [model.data?.model_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const uploadMut = useMutation({
    mutationFn: async (file: File) => {
      setUploading(true);
      try { return await uploadLogo(file); } finally { setUploading(false); }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings', 'logo'] }),
  });

  const deleteLogoMut = useMutation({
    mutationFn: deleteLogo,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings', 'logo'] }),
  });

  const saveKeyMut = useMutation({
    mutationFn: () => setApiKey(keyDraft.trim()),
    onSuccess: () => {
      setKeyDraft('');
      qc.invalidateQueries({ queryKey: ['settings', 'api-key'] });
    },
  });

  const deleteKeyMut = useMutation({
    mutationFn: deleteApiKey,
    onSuccess: () => {
      setTestResult(null);
      qc.invalidateQueries({ queryKey: ['settings', 'api-key'] });
    },
  });

  const testMut = useMutation({
    mutationFn: testApiKey,
    onSuccess: (data) => setTestResult(data),
  });

  const saveModelMut = useMutation({
    mutationFn: () => setModel(modelDraft.trim()),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings', 'model'] });
      setTestResult(null);
    },
  });

  const resetModelMut = useMutation({
    mutationFn: clearModel,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings', 'model'] });
      setTestResult(null);
    },
  });

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) uploadMut.mutate(file);
  }

  if (logo.isLoading || apiKey.isLoading || model.isLoading) return <LoadingSpinner />;

  const status = apiKey.data;
  const modelStatus = model.data;

  return (
    <>
      <h1 className="mb-3">Settings</h1>

      {/* === Anthropic API key === */}
      <div className="card hr-feature mb-3">
        <div className="card-body">
          <div className="card-title">Claude API Key</div>
          <p className="text-secondary small mb-3">
            Required for AI hat analysis (brand, model, colors, price). Stored locally in
            this app's database. Get a key at{' '}
            <a href="https://console.anthropic.com/" target="_blank" rel="noopener noreferrer">
              console.anthropic.com
            </a>.
          </p>

          {status?.configured ? (
            <div className="mb-3">
              <div className="hr-metric mb-2">
                <div className="hr-metric-label">Active key ({status.source})</div>
                <div className="hr-metric-value font-mono">{status.masked}</div>
              </div>
              <div className="d-flex gap-2 flex-wrap">
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  onClick={() => testMut.mutate()}
                  disabled={testMut.isPending}
                >
                  {testMut.isPending ? 'Testing…' : 'Test connection'}
                </button>
                <button
                  type="button"
                  className="btn btn-outline-danger btn-sm"
                  onClick={() => { if (confirm('Remove API key?')) deleteKeyMut.mutate(); }}
                >
                  Remove key
                </button>
              </div>
              {testResult && (
                <div className={`alert ${testResult.ok ? 'alert-success' : 'alert-danger'} mt-3 mb-0 small`}>
                  {testResult.ok ? '✓ ' : '✗ '}{testResult.detail}
                </div>
              )}
            </div>
          ) : (
            <p className="text-muted small mb-3">No key configured.</p>
          )}

          <label className="form-label">{status?.configured ? 'Replace key' : 'New key'}</label>
          <div className="d-flex gap-2 flex-wrap">
            <input
              type="password"
              className="form-control flex-grow-1"
              style={{ minWidth: 200 }}
              placeholder="sk-ant-..."
              value={keyDraft}
              onChange={e => setKeyDraft(e.target.value)}
              autoComplete="off"
            />
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => saveKeyMut.mutate()}
              disabled={!keyDraft.trim() || saveKeyMut.isPending}
            >
              {saveKeyMut.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
          {saveKeyMut.error && (
            <div className="alert alert-danger mt-3 mb-0 small">{String(saveKeyMut.error)}</div>
          )}
        </div>
      </div>

      {/* === Claude model === */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title">Claude Model</div>
          <p className="text-secondary small mb-3">
            Which Claude model handles hat analysis. The default is good for most cases —
            change it if you want more capability (Opus) or lower cost (Haiku). Test the
            connection above after changing to verify the model id is reachable.
          </p>
          {modelStatus && (
            <div className="hr-metric mb-3">
              <div className="hr-metric-label">Active model ({modelStatus.source})</div>
              <div className="hr-metric-value font-mono">{modelStatus.model_id}</div>
            </div>
          )}
          <label className="form-label">Model</label>
          <select
            className="form-select mb-2"
            value={modelSelect}
            onChange={e => {
              const v = e.target.value;
              setModelSelect(v);
              if (v !== OTHER) setModelDraft(v);
              else setModelDraft('');
            }}
          >
            {KNOWN_MODELS.map(m => (
              <option key={m.id} value={m.id}>{m.label}</option>
            ))}
            <option value={OTHER}>Other (enter custom ID)…</option>
          </select>
          {modelSelect === OTHER && (
            <input
              type="text"
              className="form-control mb-2"
              placeholder="claude-…"
              value={modelDraft}
              onChange={e => setModelDraft(e.target.value)}
              autoComplete="off"
              autoFocus
            />
          )}
          <div className="d-flex gap-2 flex-wrap">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => saveModelMut.mutate()}
              disabled={!modelDraft.trim() || saveModelMut.isPending || modelDraft.trim() === modelStatus?.model_id}
            >
              {saveModelMut.isPending ? 'Saving…' : 'Save'}
            </button>
            {modelStatus?.source === 'database' && (
              <button
                type="button"
                className="btn btn-outline-secondary"
                onClick={() => { if (confirm('Reset to default?')) resetModelMut.mutate(); }}
                disabled={resetModelMut.isPending}
              >
                Reset
              </button>
            )}
          </div>
          {saveModelMut.error && (
            <div className="alert alert-danger mt-3 mb-0 small">{String(saveModelMut.error)}</div>
          )}
        </div>
      </div>

      {/* === Recent analysis errors === */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-center mb-2">
            <div className="card-title mb-0">Recent Analysis Errors</div>
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              onClick={() => qc.invalidateQueries({ queryKey: ['admin', 'recent-errors'] })}
              disabled={errors.isFetching}
            >
              {errors.isFetching ? '…' : 'Refresh'}
            </button>
          </div>
          {errors.data && errors.data.length === 0 ? (
            <p className="text-secondary small mb-0">
              No analysis errors. {status?.configured ? '✓' : 'Configure a key to start analyzing.'}
            </p>
          ) : (
            <div>
              {errors.data?.map(err => (
                <Link
                  key={err.hat_id}
                  to={`/hats/${err.hat_id}`}
                  className="hr-color-row text-decoration-none"
                  style={{ paddingTop: '0.5rem' }}
                >
                  {err.photo_path ? (
                    <img
                      src={`/uploads/${err.photo_path}`}
                      alt=""
                      className="hr-thumb flex-shrink-0"
                      style={{ width: 40, height: 40 }}
                    />
                  ) : (
                    <div className="rounded flex-shrink-0" style={{ width: 40, height: 40, background: 'rgba(0,0,0,0.3)' }} />
                  )}
                  <div className="flex-grow-1" style={{ minWidth: 0 }}>
                    <div className="font-mono small" style={{ color: 'var(--neon-cyan)' }}>
                      {err.display_id || `Hat #${err.hat_id}`}
                    </div>
                    <div className="text-secondary small" style={{
                      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                    }} title={err.analysis_error || ''}>
                      {err.analysis_error || '(no message)'}
                    </div>
                  </div>
                  <div className="text-muted small font-mono" style={{ fontSize: '0.7rem' }}>
                    {err.analyzed_at ? new Date(err.analyzed_at).toLocaleString() : ''}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* === Backups === */}
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
          <div className="d-flex gap-2 mb-2 flex-wrap">
            <a href={backupDownloadUrl(true)} className="btn btn-primary" download>
              ↓ Full Backup
            </a>
            <a href={backupDownloadUrl(false)} className="btn btn-outline-primary" download>
              ↓ DB Only
            </a>
          </div>
          <p className="text-muted small mb-3" style={{ fontSize: '0.75rem' }}>
            <strong>Full</strong> = SQLite DB + every uploaded photo (hats, cases, branding).
            Restore by dropping the extracted <code>data/</code> back into <code>/data/</code>.
            <br/>
            <strong>DB only</strong> = just <code>headroom.db</code>. All hat metadata, cases,
            colors, prices — but no photos. Faster to download.
          </p>
          {backups.data && backups.data.length > 0 && (
            <div>
              <div className="hr-tier-label mb-2">Scheduled snapshots ({backups.data.length})</div>
              {backups.data.slice(0, 7).map(b => (
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

      {/* === Logo === */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title">Site Logo</div>
          <p className="text-secondary small mb-3">
            Shown in the navbar and home hero. Auto-resized to fit (96px tall).
            JPEG, PNG, WebP, or HEIC.
          </p>

          {logo.data?.logo_path ? (
            <div className="mb-3">
              <div
                className="d-block mb-2 p-3"
                style={{
                  background: 'rgba(0,0,0,0.3)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-sm)',
                  textAlign: 'center',
                }}
              >
                <img
                  src={`/uploads/${logo.data.logo_path}`}
                  alt="Current logo"
                  style={{ maxHeight: 96, objectFit: 'contain' }}
                />
              </div>
              <div className="d-flex gap-2 flex-wrap">
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  onClick={() => inputRef.current?.click()}
                  disabled={uploading}
                >
                  {uploading ? 'Uploading…' : 'Replace Logo'}
                </button>
                <button
                  type="button"
                  className="btn btn-outline-danger btn-sm"
                  onClick={() => { if (confirm('Remove logo?')) deleteLogoMut.mutate(); }}
                >
                  Remove
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              className="btn btn-outline-primary"
              onClick={() => inputRef.current?.click()}
              disabled={uploading}
            >
              {uploading ? 'Uploading…' : 'Upload Logo'}
            </button>
          )}

          <input
            ref={inputRef}
            type="file"
            accept="image/*"
            onChange={handleFileChange}
            hidden
          />

          {uploadMut.error && (
            <div className="alert alert-danger mt-3">{String(uploadMut.error)}</div>
          )}
        </div>
      </div>
    </>
  );
}
