import { useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getLogo, uploadLogo, deleteLogo,
  getApiKeyStatus, setApiKey, deleteApiKey, testApiKey,
} from '../api/settings';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

export function SettingsPage() {
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [keyDraft, setKeyDraft] = useState('');
  const [testResult, setTestResult] = useState<{ ok: boolean; detail: string } | null>(null);

  const logo = useQuery({ queryKey: ['settings', 'logo'], queryFn: getLogo });
  const apiKey = useQuery({ queryKey: ['settings', 'api-key'], queryFn: getApiKeyStatus });

  const uploadMut = useMutation({
    mutationFn: async (file: File) => {
      setUploading(true);
      try {
        return await uploadLogo(file);
      } finally {
        setUploading(false);
      }
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

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) uploadMut.mutate(file);
  }

  if (logo.isLoading || apiKey.isLoading) return <LoadingSpinner />;

  const status = apiKey.data;

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
