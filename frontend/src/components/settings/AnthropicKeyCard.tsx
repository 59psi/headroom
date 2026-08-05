import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getApiKeyStatus, setApiKey, deleteApiKey, testApiKey, getModel } from '../../api/settings';

export function AnthropicKeyCard() {
  const qc = useQueryClient();
  const apiKey = useQuery({ queryKey: ['settings', 'api-key'], queryFn: getApiKeyStatus });
  const model = useQuery({ queryKey: ['settings', 'model'], queryFn: getModel });
  const [keyDraft, setKeyDraft] = useState('');
  const [testResult, setTestResult] = useState<{ ok: boolean; detail: string } | null>(null);

  // A test result is only meaningful for the model it ran against, so drop it
  // whenever the active model changes — including when the Model card below
  // changes it.
  useEffect(() => { setTestResult(null); }, [model.data?.model_id]);

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

  const status = apiKey.data;

  // Without this the card would briefly claim "No key configured" to someone who
  // has one — the page used to hold a single spinner over all the cards instead.
  if (apiKey.isLoading) {
    return (
      <div className="card hr-feature mb-3">
        <div className="card-body">
          <div className="card-title">Claude API Key</div>
          <p className="text-secondary small mb-0">Loading…</p>
        </div>
      </div>
    );
  }

  return (
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
  );
}
