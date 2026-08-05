import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getModel, setModel, clearModel } from '../../api/settings';

// Curated list of Claude models known to support vision + tool use.
// "Other…" reveals a free-text input for anything not in the list.
const KNOWN_MODELS: { id: string; label: string }[] = [
  { id: 'claude-sonnet-4-6', label: 'Sonnet 4.6 — balanced (default)' },
  { id: 'claude-sonnet-4-5', label: 'Sonnet 4.5 — older, cheaper' },
  { id: 'claude-opus-4-7', label: 'Opus 4.7 — most capable, pricier' },
  { id: 'claude-haiku-4-5-20251001', label: 'Haiku 4.5 — fastest, cheapest' },
];
const OTHER = '__other__';

export function ClaudeModelCard() {
  const qc = useQueryClient();
  const model = useQuery({ queryKey: ['settings', 'model'], queryFn: getModel });
  const [modelDraft, setModelDraft] = useState('');
  const [modelSelect, setModelSelect] = useState<string>('');

  useEffect(() => {
    if (!model.data?.model_id) return;
    const id = model.data.model_id;
    if (!modelDraft) setModelDraft(id);
    if (!modelSelect) {
      const matches = KNOWN_MODELS.some(m => m.id === id);
      setModelSelect(matches ? id : OTHER);
    }
  }, [model.data?.model_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveModelMut = useMutation({
    mutationFn: () => setModel(modelDraft.trim()),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings', 'model'] }),
  });

  const resetModelMut = useMutation({
    mutationFn: clearModel,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings', 'model'] }),
  });

  const modelStatus = model.data;

  if (model.isLoading) {
    return (
      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title">Claude Model</div>
          <p className="text-secondary small mb-0">Loading…</p>
        </div>
      </div>
    );
  }

  return (
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
  );
}
