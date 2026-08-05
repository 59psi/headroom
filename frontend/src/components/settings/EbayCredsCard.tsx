import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getEbayCreds, setEbayCreds, deleteEbayCreds, testEbayCreds } from '../../api/settings';

export function EbayCredsCard() {
  const qc = useQueryClient();
  const ebay = useQuery({ queryKey: ['admin', 'ebay'], queryFn: getEbayCreds });
  const [ebayAppId, setEbayAppId] = useState('');
  const [ebayCertId, setEbayCertId] = useState('');
  const [ebayTestResult, setEbayTestResult] = useState<{ ok: boolean; stage: string; detail: string } | null>(null);

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

  return (
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
  );
}
