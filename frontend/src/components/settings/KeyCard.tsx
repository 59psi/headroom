import { useEffect, useState, type ReactNode } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ErrorNote } from '../common/ErrorNote';
import type { ApiKeyStatus, ApiKeyTestResult } from '../../types';

/**
 * One external API key: status, replace, remove, optionally test.
 *
 * The frontend twin of the backend's `KeyProvider` — there, one frozen
 * record per provider drives the resolver AND the generated routes, so adding
 * a key is one entry. Here it was two cards, ~90% the same markup, and the
 * Google one had drifted: no loading state, so it briefly claimed "No key
 * configured" to someone who had one — the exact bug the Claude card had
 * already fixed. One component, one fix.
 */
export interface KeyProviderSpec {
  /** Card heading, e.g. "Claude API Key". */
  title: string;
  /** Query key under `['settings', …]`; also what save/remove invalidate. */
  queryKey: readonly [string, string];
  getStatus: () => Promise<ApiKeyStatus>;
  setKey: (key: string) => Promise<ApiKeyStatus>;
  deleteKey: () => Promise<void>;
  /** `id` of the input — a label needs it, and tests find the field by it. */
  inputId: string;
  placeholder: string;
  blurb: ReactNode;
  noKeyText: string;
  removeConfirm: string;
  /** `hr-feature` styling for the key the app is built around. */
  featured?: boolean;
  /**
   * Optional "Test connection". A result is only meaningful for the model it
   * ran against, so the card drops it whenever `resetOn` changes — the Claude
   * card passes the active model id, which the Model card next door edits.
   */
  test?: {
    run: () => Promise<ApiKeyTestResult>;
    resetOn?: string | undefined;
  };
}

export function KeyCard({ provider }: { provider: KeyProviderSpec }) {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: provider.queryKey, queryFn: provider.getStatus });
  const [draft, setDraft] = useState('');
  const [testResult, setTestResult] = useState<ApiKeyTestResult | null>(null);
  const resetOn = provider.test?.resetOn;
  useEffect(() => { setTestResult(null); }, [resetOn]);

  const saveMut = useMutation({
    mutationFn: () => provider.setKey(draft.trim()),
    onSuccess: () => {
      setDraft('');
      qc.invalidateQueries({ queryKey: provider.queryKey });
    },
  });
  const deleteMut = useMutation({
    mutationFn: provider.deleteKey,
    onSuccess: () => {
      setTestResult(null);
      qc.invalidateQueries({ queryKey: provider.queryKey });
    },
  });
  const testMut = useMutation({
    mutationFn: () => provider.test!.run(),
    onSuccess: (data) => setTestResult(data),
  });

  const cardClass = `card ${provider.featured ? 'hr-feature ' : ''}mb-3`;

  // Without this the card would briefly claim "No key configured" to someone
  // who has one — the page used to hold a single spinner over every card.
  if (status.isLoading) {
    return (
      <div className={cardClass}>
        <div className="card-body">
          <div className="card-title">{provider.title}</div>
          <p className="text-secondary small mb-0">Loading…</p>
        </div>
      </div>
    );
  }

  const configured = status.data?.configured ?? false;

  return (
    <div className={cardClass}>
      <div className="card-body">
        <div className="card-title">{provider.title}</div>
        <p className="text-secondary small mb-3">{provider.blurb}</p>

        {configured && status.data ? (
          <div className="mb-3">
            <div className="hr-metric mb-2">
              <div className="hr-metric-label">Active key ({status.data.source})</div>
              <div className="hr-metric-value font-mono">{status.data.masked}</div>
            </div>
            <div className="d-flex gap-2 flex-wrap">
              {provider.test && (
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  onClick={() => testMut.mutate()}
                  disabled={testMut.isPending}
                >
                  {testMut.isPending ? 'Testing…' : 'Test connection'}
                </button>
              )}
              <button
                type="button"
                className="btn btn-outline-danger btn-sm"
                onClick={() => { if (confirm(provider.removeConfirm)) deleteMut.mutate(); }}
                disabled={deleteMut.isPending}
              >
                Remove key
              </button>
            </div>
            {testResult && (
              <div className={`alert ${testResult.ok ? 'alert-success' : 'alert-danger'} mt-3 mb-0 small`}>
                {testResult.ok ? '✓ ' : '✗ '}{testResult.detail}
              </div>
            )}
            <ErrorNote of={[testMut, deleteMut]} className="mt-3" />
          </div>
        ) : status.isSuccess ? (
          <p className="text-muted small mb-3">{provider.noKeyText}</p>
        ) : (
          <ErrorNote of={status} what="Could not read this key's status" className="mb-3" />
        )}

        <label className="form-label" htmlFor={provider.inputId}>{configured ? 'Replace key' : 'New key'}</label>
        <div className="d-flex gap-2 flex-wrap">
          <input
            id={provider.inputId}
            type="password"
            className="form-control flex-grow-1"
            style={{ minWidth: 200 }}
            placeholder={provider.placeholder}
            value={draft}
            onChange={e => setDraft(e.target.value)}
            autoComplete="off"
          />
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => saveMut.mutate()}
            disabled={!draft.trim() || saveMut.isPending}
          >
            {saveMut.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
        <ErrorNote of={saveMut} className="mt-3" />
      </div>
    </div>
  );
}
