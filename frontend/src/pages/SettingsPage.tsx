import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getLogo, uploadLogo, deleteLogo,
  getApiKeyStatus, setApiKey, deleteApiKey, testApiKey,
  getGoogleVisionKeyStatus, setGoogleVisionKey, deleteGoogleVisionKey,
  getModel, setModel, clearModel,
  getMdnsStatus,
  getRecentErrors, listBackups, backupDownloadUrl,
  getActivityLog, getEbayCreds, setEbayCreds, deleteEbayCreds, testEbayCreds,
  inventoryReportUrl,
} from '../api/settings';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import {
  changePassword, createShareLink, deletePasskey, getMe, listPasskeys,
  listShareLinks, logout, passkeyRegisterOptions, passkeyRegisterVerify,
  revokeShareLink, rotateApiToken,
} from '../api/auth';
import { createPasskey, passkeysSupported } from '../lib/webauthn';
import { apiFetch } from '../api/client';

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
  const [visionKeyDraft, setVisionKeyDraft] = useState('');

  const logo = useQuery({ queryKey: ['settings', 'logo'], queryFn: getLogo });
  const apiKey = useQuery({ queryKey: ['settings', 'api-key'], queryFn: getApiKeyStatus });
  const visionKey = useQuery({ queryKey: ['settings', 'google-vision-key'], queryFn: getGoogleVisionKeyStatus });
  const model = useQuery({ queryKey: ['settings', 'model'], queryFn: getModel });
  const errors = useQuery({ queryKey: ['admin', 'recent-errors'], queryFn: () => getRecentErrors(20) });
  const backups = useQuery({ queryKey: ['admin', 'backups'], queryFn: listBackups });
  const activity = useQuery({ queryKey: ['admin', 'activity'], queryFn: () => getActivityLog(50) });
  const ebay = useQuery({ queryKey: ['admin', 'ebay'], queryFn: getEbayCreds });
  const mdns = useQuery({ queryKey: ['settings', 'mdns'], queryFn: getMdnsStatus });

  const [ebayAppId, setEbayAppId] = useState('');
  const [ebayCertId, setEbayCertId] = useState('');
  const [ebayTestResult, setEbayTestResult] = useState<{ ok: boolean; stage: string; detail: string } | null>(null);

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

  const saveVisionKeyMut = useMutation({
    mutationFn: () => setGoogleVisionKey(visionKeyDraft.trim()),
    onSuccess: () => {
      setVisionKeyDraft('');
      qc.invalidateQueries({ queryKey: ['settings', 'google-vision-key'] });
    },
  });

  const deleteVisionKeyMut = useMutation({
    mutationFn: deleteGoogleVisionKey,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings', 'google-vision-key'] }),
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

  const saveEbayMut = useMutation({
    mutationFn: () => setEbayCreds({ app_id: ebayAppId.trim(), cert_id: ebayCertId.trim() }),
    onSuccess: () => {
      setEbayAppId('');
      setEbayCertId('');
      qc.invalidateQueries({ queryKey: ['admin', 'ebay'] });
    },
  });

  const deleteEbayMut = useMutation({
    mutationFn: deleteEbayCreds,
    onSuccess: () => {
      setEbayTestResult(null);
      qc.invalidateQueries({ queryKey: ['admin', 'ebay'] });
    },
  });

  const testEbayMut = useMutation({
    mutationFn: testEbayCreds,
    onSuccess: (data) => setEbayTestResult(data),
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

      {/* === Google Vision fallback key === */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title">Google Vision Key (fallback)</div>
          <p className="text-secondary small mb-3">
            Optional. When Claude is unavailable, hats still get color swatches from the
            photo cutout — add a Google Cloud Vision API key to also detect the brand
            from its logo. Create one at{' '}
            <a href="https://console.cloud.google.com/apis/library/vision.googleapis.com" target="_blank" rel="noopener noreferrer">
              console.cloud.google.com
            </a>{' '}
            (enable the Cloud Vision API, then create an API key).
          </p>

          {visionKey.data?.configured ? (
            <div className="mb-3">
              <div className="hr-metric mb-2">
                <div className="hr-metric-label">Active key ({visionKey.data.source})</div>
                <div className="hr-metric-value font-mono">{visionKey.data.masked}</div>
              </div>
              <button
                type="button"
                className="btn btn-outline-danger btn-sm"
                onClick={() => { if (confirm('Remove Google Vision key?')) deleteVisionKeyMut.mutate(); }}
              >
                Remove key
              </button>
            </div>
          ) : (
            <p className="text-muted small mb-3">No key configured — fallback provides colors only.</p>
          )}

          <label className="form-label">{visionKey.data?.configured ? 'Replace key' : 'New key'}</label>
          <div className="d-flex gap-2 flex-wrap">
            <input
              type="password"
              className="form-control flex-grow-1"
              style={{ minWidth: 200 }}
              placeholder="AIzaSy..."
              value={visionKeyDraft}
              onChange={e => setVisionKeyDraft(e.target.value)}
              autoComplete="off"
            />
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => saveVisionKeyMut.mutate()}
              disabled={!visionKeyDraft.trim() || saveVisionKeyMut.isPending}
            >
              {saveVisionKeyMut.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
          {saveVisionKeyMut.error && (
            <div className="alert alert-danger mt-3 mb-0 small">{String(saveVisionKeyMut.error)}</div>
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

      {/* === eBay credentials === */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title">eBay Comparable Listings (optional)</div>
          <p className="text-secondary small mb-3">
            When configured, hat analysis pulls live comparable-listings prices
            from eBay's Browse API. Free 5,000 calls/day. Get a key at{' '}
            <a href="https://developer.ebay.com/" target="_blank" rel="noopener noreferrer">
              developer.ebay.com
            </a>{' '}— go to <em>My Account → Application Keysets</em> and copy
            the <strong>Production</strong> App ID + Cert ID (Sandbox keys won't
            work — they fail with a 401).
          </p>
          {ebay.data?.configured ? (
            <div className="mb-3">
              <div className="hr-metric mb-2">
                <div className="hr-metric-label">
                  Active App ID · {ebay.data.marketplace}
                  {ebay.data.detected_env && (
                    <span style={{
                      marginLeft: 8, padding: '1px 6px', borderRadius: 4,
                      fontSize: '0.65rem', textTransform: 'uppercase',
                      letterSpacing: '0.06em',
                      background: ebay.data.detected_env === 'production'
                        ? 'rgba(57, 255, 20, 0.15)'
                        : ebay.data.detected_env === 'sandbox'
                          ? 'rgba(255, 56, 96, 0.18)'
                          : 'rgba(177, 78, 255, 0.15)',
                      color: ebay.data.detected_env === 'production'
                        ? 'var(--neon-green)'
                        : ebay.data.detected_env === 'sandbox'
                          ? 'var(--neon-red)'
                          : 'var(--neon-purple)',
                    }}>{ebay.data.detected_env}</span>
                  )}
                </div>
                <div className="hr-metric-value font-mono">{ebay.data.app_id_masked}</div>
                {ebay.data.detected_env === 'sandbox' && (
                  <div className="text-danger small mt-1" style={{ fontSize: '0.7rem' }}>
                    These are SANDBOX keys — they will fail with 401. Replace with a Production keyset.
                  </div>
                )}
              </div>
              <div className="d-flex gap-2 flex-wrap">
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  onClick={() => testEbayMut.mutate()}
                  disabled={testEbayMut.isPending}
                >
                  {testEbayMut.isPending ? 'Testing…' : 'Test connection'}
                </button>
                <button
                  type="button"
                  className="btn btn-outline-danger btn-sm"
                  onClick={() => { if (confirm('Remove eBay credentials?')) deleteEbayMut.mutate(); }}
                >Remove</button>
              </div>
              {ebayTestResult && (
                <div className={`alert ${ebayTestResult.ok ? 'alert-success' : 'alert-danger'} mt-3 mb-0 small`}>
                  {ebayTestResult.ok ? '✓ ' : '✗ '}{ebayTestResult.detail}
                  {!ebayTestResult.ok && (
                    <div className="text-muted small mt-1" style={{ fontSize: '0.7rem' }}>
                      Failed at: <code>{ebayTestResult.stage}</code>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <p className="text-muted small mb-3">
              Not configured — eBay tile shows the search deep-link only, no live prices.
            </p>
          )}
          <label className="form-label">App ID (Client ID)</label>
          <input
            type="text"
            className="form-control mb-2"
            value={ebayAppId}
            onChange={e => setEbayAppId(e.target.value)}
            autoComplete="off"
          />
          <label className="form-label">Cert ID (Client Secret)</label>
          <input
            type="password"
            className="form-control mb-2"
            value={ebayCertId}
            onChange={e => setEbayCertId(e.target.value)}
            autoComplete="off"
          />
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => saveEbayMut.mutate()}
            disabled={!ebayAppId.trim() || !ebayCertId.trim() || saveEbayMut.isPending}
          >
            {saveEbayMut.isPending ? 'Saving…' : 'Save'}
          </button>
          {saveEbayMut.error && (
            <div className="alert alert-danger mt-3 mb-0 small">{String(saveEbayMut.error)}</div>
          )}
        </div>
      </div>

      {/* === LAN discovery (read-only) === */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title">LAN Discovery (mDNS)</div>
          <p className="text-secondary small mb-3">
            Read-only — configured with the <code>HEADROOM_MDNS_*</code> environment
            variables. On Docker the name only reaches your network with the
            <code> docker-compose.mdns.yml</code> overlay (host networking); for
            Face&nbsp;ID / passkeys on the LAN name, use the
            <code> docker-compose.https-lan.yml</code> overlay instead.
          </p>
          {mdns.data && (mdns.data.advertising ? (
            <div className="hr-metric">
              <div className="hr-metric-label">Advertising → {mdns.data.ip}</div>
              <div className="hr-metric-value font-mono">
                <a href={mdns.data.url ?? '#'} target="_blank" rel="noopener noreferrer">
                  {mdns.data.url}
                </a>
              </div>
            </div>
          ) : (
            <div className="hr-metric">
              <div className="hr-metric-label">
                {mdns.data.enabled ? 'Enabled — not advertising' : 'Disabled'}
              </div>
              <div className="hr-metric-value font-mono">
                {mdns.data.error ?? mdns.data.hostname}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* === Activity log === */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-center mb-2">
            <div className="card-title mb-0">Recent Activity</div>
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              onClick={() => qc.invalidateQueries({ queryKey: ['admin', 'activity'] })}
              disabled={activity.isFetching}
            >{activity.isFetching ? '…' : 'Refresh'}</button>
          </div>
          {(activity.data?.length ?? 0) === 0 ? (
            <p className="text-secondary small mb-0">No activity logged yet.</p>
          ) : (
            <div>
              {activity.data?.slice(0, 25).map(row => (
                <div key={row.id} className="hr-color-row" style={{ paddingTop: '0.5rem' }}>
                  <div className="flex-grow-1" style={{ minWidth: 0 }}>
                    <div className="small" style={{
                      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                    }}>{row.summary}</div>
                    <div className="text-muted small font-mono" style={{ fontSize: '0.7rem' }}>
                      {row.kind}
                    </div>
                  </div>
                  <div className="text-muted small font-mono" style={{ fontSize: '0.7rem' }}>
                    {new Date(row.occurred_at).toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* === Share to Headroom (iOS Shortcut + Android PWA) === */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title">Share Photos to Headroom</div>
          <p className="text-secondary small mb-3">
            <strong>Android Chrome:</strong> install Headroom as a PWA (browser
            menu → Install app), then "Share to Headroom" appears in the system
            share sheet automatically — selected photos route into a bulk-import
            job.
          </p>
          <p className="text-secondary small mb-3">
            <strong>iOS Safari</strong> doesn't support Web Share Target yet,
            so use a one-time Shortcut. Open the Shortcuts app → tap <strong>+</strong>
            → add these actions in order:
          </p>
          <ol className="text-secondary small mb-3" style={{ paddingLeft: '1.2rem' }}>
            <li className="mb-1"><strong>Receive</strong> Images from Share Sheet (toggle "Show in Share Sheet" ON)</li>
            <li className="mb-1"><strong>Get Contents of URL</strong>
              <ul style={{ paddingLeft: '1.2rem', marginTop: '0.25rem' }}>
                <li>URL: <code style={{ fontSize: '0.85em' }}>{`${window.location.origin}/api/hats/import`}</code></li>
                <li>Method: <code>POST</code></li>
                <li>Headers → add: key=<code>Authorization</code>, value=<code>Bearer YOUR-API-TOKEN</code> (copy the token from the <strong>Account</strong> card below)</li>
                <li>Request Body: <code>Form</code></li>
                <li>Add field: key=<code>photos</code>, type=<code>File</code>, value=<em>Shortcut Input</em></li>
              </ul>
            </li>
            <li>Name it "Add to Headroom" and you're done.</li>
          </ol>
          <p className="text-muted small mb-0" style={{ fontSize: '0.75rem' }}>
            Now open Photos → select multiple → Share → "Add to Headroom".
            Each shared photo becomes a hat with the same defaults the Bulk Import
            page uses (style: A-Game · size: classic · condition: new) — edit
            after Claude finishes analyzing.
          </p>
        </div>
      </div>

      {/* === Inventory report === */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title">Inventory Report</div>
          <p className="text-secondary small mb-3">
            Print-friendly HTML — use your browser's <strong>Print → Save as PDF</strong>
            to export. Includes thumbnails, totals, brand / model, condition, location,
            and best-available current value for every hat.
          </p>
          <div className="d-flex gap-2 flex-wrap">
            <a href={inventoryReportUrl()} target="_blank" rel="noopener noreferrer" className="btn btn-primary">
              Open Report (active hats)
            </a>
            <a href={inventoryReportUrl({ includeDisposed: true })} target="_blank" rel="noopener noreferrer" className="btn btn-outline-primary">
              Include Disposed
            </a>
          </div>
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

      <ColorwayCatalogCard />
      <PurchasesCard />
      <AccountCard />
      <ShareLinksCard />
    </>
  );
}


/* ===================== Account (auth) card ===================== */

function AccountCard() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ['auth', 'me'], queryFn: getMe });
  const passkeys = useQuery({ queryKey: ['auth', 'passkeys'], queryFn: listPasskeys });
  const [showToken, setShowToken] = useState(false);
  const [curPw, setCurPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [pwMsg, setPwMsg] = useState<string | null>(null);
  const [pkError, setPkError] = useState<string | null>(null);

  const rotateMut = useMutation({
    mutationFn: rotateApiToken,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['auth', 'me'] }),
  });

  const pwMut = useMutation({
    mutationFn: () => changePassword(curPw, newPw),
    onSuccess: () => { setPwMsg('Password changed.'); setCurPw(''); setNewPw(''); },
    onError: (e) => setPwMsg(String(e instanceof Error ? e.message : e)),
  });

  async function addPasskey() {
    setPkError(null);
    try {
      const { state_id, options } = await passkeyRegisterOptions();
      const credential = await createPasskey(options);
      const name = prompt('Name this passkey (e.g. "iPhone")', 'Passkey') || 'Passkey';
      await passkeyRegisterVerify(state_id, credential, name);
      qc.invalidateQueries({ queryKey: ['auth', 'passkeys'] });
    } catch (e) {
      setPkError(String(e instanceof Error ? e.message : e));
    }
  }

  async function signOut() {
    await logout();
    window.location.assign('/login');
  }

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Account</div>
        <p className="text-secondary small mb-3">
          Signed in as <span className="font-mono">{me.data?.username ?? '…'}</span>
        </p>

        <div className="mb-3">
          <div className="hr-metric-label mb-1">API token (for the iOS Shortcut — sent as a Bearer header)</div>
          <div className="d-flex gap-2 flex-wrap align-items-center">
            <code className="small" style={{ wordBreak: 'break-all' }}>
              {showToken ? me.data?.api_token : '••••••••••••••••'}
            </code>
            <button type="button" className="btn btn-outline-secondary btn-sm" onClick={() => setShowToken(!showToken)}>
              {showToken ? 'Hide' : 'Show'}
            </button>
            <button
              type="button"
              className="btn btn-outline-danger btn-sm"
              onClick={() => { if (confirm('Rotate token? The old one stops working immediately.')) rotateMut.mutate(); }}
            >
              Rotate
            </button>
          </div>
        </div>

        <div className="mb-3">
          <div className="hr-metric-label mb-1">Passkeys {passkeysSupported() ? '' : '(needs HTTPS or localhost)'}</div>
          {(passkeys.data ?? []).map(p => (
            <div key={p.id} className="d-flex align-items-center gap-2 small mb-1">
              🔑 {p.name}
              <button
                type="button"
                className="btn btn-link btn-sm p-0"
                style={{ color: 'var(--neon-red)' }}
                onClick={async () => {
                  if (confirm(`Remove passkey "${p.name}"?`)) {
                    await deletePasskey(p.id);
                    qc.invalidateQueries({ queryKey: ['auth', 'passkeys'] });
                  }
                }}
              >remove</button>
            </div>
          ))}
          {passkeysSupported() && (
            <button type="button" className="btn btn-outline-secondary btn-sm" onClick={addPasskey}>
              + Add passkey (Face ID / Touch ID)
            </button>
          )}
          {pkError && <div className="alert alert-danger small mt-2 mb-0">{pkError}</div>}
        </div>

        <div className="mb-3">
          <div className="hr-metric-label mb-1">Change password</div>
          <div className="d-flex gap-2 flex-wrap">
            <input type="password" className="form-control" style={{ maxWidth: 200 }} placeholder="Current"
              value={curPw} onChange={e => setCurPw(e.target.value)} autoComplete="current-password" />
            <input type="password" className="form-control" style={{ maxWidth: 200 }} placeholder="New (8+ chars)"
              value={newPw} onChange={e => setNewPw(e.target.value)} autoComplete="new-password" />
            <button type="button" className="btn btn-outline-primary"
              disabled={!curPw || newPw.length < 8 || pwMut.isPending}
              onClick={() => pwMut.mutate()}>
              Change
            </button>
          </div>
          {pwMsg && <div className="small mt-1 text-secondary">{pwMsg}</div>}
        </div>

        <button type="button" className="btn btn-outline-danger" onClick={signOut}>
          Sign out
        </button>
      </div>
    </div>
  );
}

/* ===================== Share links card ===================== */

function ShareLinksCard() {
  const qc = useQueryClient();
  const links = useQuery({ queryKey: ['share-links'], queryFn: listShareLinks });
  const [label, setLabel] = useState('');
  const [copied, setCopied] = useState<number | null>(null);

  const createMut = useMutation({
    mutationFn: () => createShareLink(label.trim() || 'Shared collection'),
    onSuccess: () => { setLabel(''); qc.invalidateQueries({ queryKey: ['share-links'] }); },
  });

  const active = (links.data ?? []).filter(l => !l.revoked_at);

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Share Links</div>
        <p className="text-secondary small mb-3">
          Read-only links to show off the collection — no login needed to view.
          Revoke any time.
        </p>

        {active.map(l => (
          <div key={l.id} className="d-flex align-items-center gap-2 small mb-2 flex-wrap">
            <span className="fw-semibold">{l.label}</span>
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              onClick={async () => {
                await navigator.clipboard.writeText(`${window.location.origin}${l.url_path}`);
                setCopied(l.id);
                setTimeout(() => setCopied(null), 1500);
              }}
            >{copied === l.id ? 'Copied!' : 'Copy link'}</button>
            <button
              type="button"
              className="btn btn-link btn-sm p-0"
              style={{ color: 'var(--neon-red)' }}
              onClick={async () => {
                if (confirm('Revoke this link? Anyone holding it loses access.')) {
                  await revokeShareLink(l.id);
                  qc.invalidateQueries({ queryKey: ['share-links'] });
                }
              }}
            >revoke</button>
          </div>
        ))}
        {active.length === 0 && <p className="text-muted small">No active share links.</p>}

        <div className="d-flex gap-2 mt-2">
          <input className="form-control" style={{ maxWidth: 260 }} placeholder="Label (e.g. For the group chat)"
            value={label} onChange={e => setLabel(e.target.value)} />
          <button type="button" className="btn btn-primary" onClick={() => createMut.mutate()} disabled={createMut.isPending}>
            Create link
          </button>
        </div>
      </div>
    </div>
  );
}


/* ===================== Colorway catalog card ===================== */

function ColorwayCatalogCard() {
  const qc = useQueryClient();
  const models = useQuery({
    queryKey: ['meta', 'colorways', 'models'],
    queryFn: () => apiFetch<{ value: string }[]>('/api/meta/colorways'),
  });

  const refreshMut = useMutation({
    mutationFn: () => apiFetch<{ titles_seen: number; new_entries: number; catalog_total: number }>(
      '/api/admin/colorways/refresh', { method: 'POST' },
    ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['meta', 'colorways'] }),
  });

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Colorway Catalog</div>
        <p className="text-secondary small mb-3">
          Model + colorway names harvested from Melin Recap's live listings —
          includes sold-out drops that are long gone from melin.com. Powers the
          autocomplete on the Edit Hat form and purchase matching.
        </p>
        <div className="d-flex gap-2 align-items-center flex-wrap">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => refreshMut.mutate()}
            disabled={refreshMut.isPending}
          >
            {refreshMut.isPending ? 'Harvesting… (takes ~a minute)' : 'Refresh from Melin Recap'}
          </button>
          <span className="text-secondary small font-mono">
            {models.data?.length ?? 0} models known
          </span>
        </div>
        {refreshMut.data && (
          <div className="alert alert-success small mt-3 mb-0">
            ✓ Swept {refreshMut.data.titles_seen} live listings — {refreshMut.data.new_entries} new
            entries, {refreshMut.data.catalog_total} total in catalog.
          </div>
        )}
        {refreshMut.error && (
          <div className="alert alert-danger small mt-3 mb-0">{String(refreshMut.error)}</div>
        )}
      </div>
    </div>
  );
}

/* ===================== Purchases card ===================== */

interface PurchaseRow {
  id: number; order_ref: string | null; order_date: string | null;
  item_title: string; price: number | null; hat_id: number | null;
}

function PurchasesCard() {
  const qc = useQueryClient();
  const purchases = useQuery({
    queryKey: ['admin', 'purchases'],
    queryFn: () => apiFetch<PurchaseRow[]>('/api/admin/purchases'),
  });

  const rematchMut = useMutation({
    mutationFn: () => apiFetch<{ matched: number; unmatched: number }>(
      '/api/admin/purchases/match', { method: 'POST' },
    ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'purchases'] });
      qc.invalidateQueries({ queryKey: ['hats'] });
    },
  });

  const rows = purchases.data ?? [];
  const linked = rows.filter(r => r.hat_id != null).length;

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Purchase History</div>
        <p className="text-secondary small mb-3">
          Order line items imported from your Melin emails. Matched purchases set a
          hat's colorway and cost basis (what you actually paid).
        </p>
        <div className="d-flex gap-2 align-items-center flex-wrap mb-2">
          <span className="text-secondary small font-mono">
            {rows.length} purchases · {linked} linked to hats
          </span>
          {rows.length > 0 && (
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              onClick={() => rematchMut.mutate()}
              disabled={rematchMut.isPending}
            >
              Re-run matching
            </button>
          )}
        </div>
        {rematchMut.data && (
          <div className="small text-secondary mb-2">
            ✓ matched {rematchMut.data.matched}, {rematchMut.data.unmatched} still unmatched
          </div>
        )}
        {rows.slice(0, 8).map(r => (
          <div key={r.id} className="small d-flex justify-content-between gap-2 mb-1">
            <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {r.hat_id != null ? '🔗 ' : '· '}{r.item_title}
            </span>
            <span className="font-mono text-secondary">
              {r.price != null ? `$${r.price.toFixed(2)}` : '—'}
            </span>
          </div>
        ))}
        {rows.length > 8 && <div className="small text-muted">…and {rows.length - 8} more</div>}
      </div>
    </div>
  );
}
