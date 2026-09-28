import { useId, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getEbayCreds, setEbayCreds, deleteEbayCreds, testEbayCreds } from '../../api/settings';
import type { EbayCredsStatus } from '../../types';
import { ErrorNote } from '../common/ErrorNote';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';
import { useConfirm } from '../ui/Dialogs';

/** Which eBay environment the saved App ID belongs to, as a pill. Production
 *  is the only one that works — a Sandbox keyset fails every call with a 401,
 *  which from the outside looks exactly like a wrong key. */
function envPill(env: EbayCredsStatus['detected_env']) {
  if (env === 'production') return <StatusPill tone="ok">Production</StatusPill>;
  if (env === 'sandbox') return <StatusPill tone="error">Sandbox</StatusPill>;
  if (env === 'unknown') return <StatusPill tone="info">Unknown environment</StatusPill>;
  return null;
}

type TestResult = { ok: boolean; stage: string; detail: string };

/**
 * The card's state in one word — and only as strong a word as the evidence.
 *
 * A saved keyset is CONFIGURED; nothing about it says it connects. "Connected"
 * is earned by a passing Test connection in this visit, and a failing one says
 * "Failing". A sandbox keyset is known bad before any test — it 401s on every
 * call — so it outranks a plain "Configured".
 */
function statePill(status: EbayCredsStatus, test: TestResult | null) {
  if (!status.configured) return <StatusPill tone="off">Not set</StatusPill>;
  if (test?.ok) return <StatusPill tone="ok">Connected</StatusPill>;
  if (test) return <StatusPill tone="error" title={test.detail}>Failing</StatusPill>;
  if (status.detected_env === 'sandbox') return <StatusPill tone="error">Sandbox keys</StatusPill>;
  return <StatusPill tone="ok">Configured</StatusPill>;
}

export function EbayCredsCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const formId = useId();
  const ebay = useQuery({ queryKey: ['admin', 'ebay'], queryFn: getEbayCreds });
  const [ebayAppId, setEbayAppId] = useState('');
  const [ebayCertId, setEbayCertId] = useState('');
  const [ebayTestResult, setEbayTestResult] = useState<TestResult | null>(null);

  const saveEbayMut = useMutation({
    mutationFn: () => setEbayCreds({ app_id: ebayAppId.trim(), cert_id: ebayCertId.trim() }),
    onSuccess: saved => {
      setEbayAppId('');
      setEbayCertId('');
      // A result for the OLD keyset says nothing about these.
      setEbayTestResult(null);
      toast.success('eBay credentials saved');
      // The PUT answers with the new status, so the card flips to Configured
      // (masked id, detected environment) without waiting on a refetch.
      // "Connected" still waits for a passing Test connection — see statePill.
      qc.setQueryData(['admin', 'ebay'], saved);
      qc.invalidateQueries({ queryKey: ['admin', 'ebay'] });
    },
  });

  const deleteEbayMut = useMutation({
    mutationFn: deleteEbayCreds,
    onSuccess: () => {
      setEbayTestResult(null);
      toast.success('eBay credentials removed');
      qc.invalidateQueries({ queryKey: ['admin', 'ebay'] });
    },
  });

  const testEbayMut = useMutation({
    mutationFn: testEbayCreds,
    onSuccess: (data) => setEbayTestResult(data),
  });

  // A plain-string body, so the no-provider `window.confirm` fallback still
  // states what removing costs (it cannot render markup).
  const remove = async () => {
    const ok = await confirm({
      title: 'Remove eBay credentials?',
      body:
        'Removes the saved App ID and Cert ID. Without a keyset, analysis stops '
        + 'pulling live comparable-listing prices and the eBay tile shows the '
        + 'search deep-link only. You can add a keyset again at any time.',
      confirmLabel: 'Remove credentials',
      tone: 'danger',
    });
    if (ok) deleteEbayMut.mutate();
  };

  const configured = ebay.data?.configured ?? false;
  const canSave = !!ebayAppId.trim() && !!ebayCertId.trim() && !saveEbayMut.isPending;

  return (
    <Panel
      title="eBay comparable listings"
      status={ebay.data && statePill(ebay.data, ebayTestResult)}
      description="Optional. Adds live eBay comparable-listing prices to hat analysis — free for 5,000 calls a day."
      help={
        <p>
          When configured, hat analysis pulls live comparable-listings prices from
          eBay&rsquo;s Browse API. Get a key at{' '}
          <a href="https://developer.ebay.com/" target="_blank" rel="noopener noreferrer">
            developer.ebay.com
          </a>{' '}— go to <em>My Account → Application Keysets</em> and copy the{' '}
          <strong>Production</strong> App ID + Cert ID (Sandbox keys won&rsquo;t
          work — they fail with a 401).
        </p>
      }
      footer={
        <>
          <button
            type="submit"
            form={formId}
            className="btn btn-primary"
            disabled={!canSave}
          >
            {saveEbayMut.isPending ? 'Saving…' : configured ? 'Replace credentials' : 'Save credentials'}
          </button>
          <ErrorNote of={saveEbayMut} what="Could not save" className="w-100" />
        </>
      }
    >
      {ebay.isLoading && <Skeleton height={72} />}
      <ErrorNote of={[ebay, deleteEbayMut, testEbayMut]} className="mb-3" />

      {configured && ebay.data ? (
        <div className="mb-3">
          <div className="hr-metric">
            <div className="hr-sd-cred-head">
              <span className="hr-metric-label mb-0">
                Active App ID · {ebay.data.marketplace}
              </span>
              {envPill(ebay.data.detected_env)}
            </div>
            <div className="hr-metric-value">{ebay.data.app_id_masked}</div>
            {ebay.data.detected_env === 'sandbox' && (
              <div className="text-danger small mt-1">
                These are <strong>sandbox</strong> keys — they will fail with a 401.
                Replace them with a Production keyset.
              </div>
            )}
          </div>
          <div className="d-flex gap-2 flex-wrap mt-2">
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
              onClick={remove}
              disabled={deleteEbayMut.isPending}
            >{deleteEbayMut.isPending ? 'Removing…' : 'Remove'}</button>
          </div>
          {ebayTestResult && (
            <div
              className={`alert ${ebayTestResult.ok ? 'alert-success' : 'alert-danger'} mt-3 mb-0 small`}
              role="status"
            >
              {ebayTestResult.ok ? '✓ ' : '✗ '}{ebayTestResult.detail}
              {!ebayTestResult.ok && (
                <div className="hr-sd-legend mt-1">
                  Failed at: <code>{ebayTestResult.stage}</code>
                </div>
              )}
            </div>
          )}
        </div>
      ) : ebay.isSuccess ? (
        <p className="text-muted small mb-3">
          Not configured — the eBay tile shows the search deep-link only, no live prices.
        </p>
      ) : null}

      <form
        id={formId}
        onSubmit={e => {
          e.preventDefault();
          if (canSave) saveEbayMut.mutate();
        }}
      >
        {configured && <span className="hr-eyebrow">Replace with a new keyset</span>}
        <div className="mb-3">
          <label className="form-label" htmlFor="ebay-app-id">App ID (Client ID)</label>
          <input
            id="ebay-app-id"
            type="text"
            className="form-control font-mono"
            value={ebayAppId}
            onChange={e => setEbayAppId(e.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        <div>
          <label className="form-label" htmlFor="ebay-cert-id">Cert ID (Client Secret)</label>
          <input
            id="ebay-cert-id"
            type="password"
            className="form-control font-mono"
            value={ebayCertId}
            onChange={e => setEbayCertId(e.target.value)}
            autoComplete="off"
          />
        </div>
      </form>
    </Panel>
  );
}
