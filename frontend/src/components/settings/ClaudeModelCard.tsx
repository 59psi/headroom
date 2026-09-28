import { useState, type FormEvent, type ReactNode } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getModel, setModel, clearModel, getApiKeyStatus, testApiKey } from '../../api/settings';
import { ErrorNote } from '../common/ErrorNote';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { SaveState, mutationSaveStatus } from '../ui/SaveState';
import { useToast } from '../ui/Toast';
import { useConfirm } from '../ui/Dialogs';
import type { ApiKeyTestResult, ModelStatus } from '../../types';

// Curated list of Claude models known to support vision + tool use, which is
// all this app needs from a model. Deliberately relative ("cheapest", not
// "$1/MTok") — Anthropic's price list changes and a hardcoded number rots.
//
// Legacy ids are kept listed rather than dropped: an install that saved one
// stays on a named option instead of silently falling through to "Other…"
// with its id in a free-text box. They still work; they're just superseded.
// "Other…" covers anything not here, including models newer than this build.
const CURRENT_MODELS: { id: string; label: string }[] = [
  { id: 'claude-sonnet-5', label: 'Sonnet 5 — balanced' },
  { id: 'claude-haiku-4-5-20251001', label: 'Haiku 4.5 — fastest, cheapest' },
  { id: 'claude-opus-5', label: 'Opus 5 — more capable, pricier' },
  { id: 'claude-fable-5-1', label: 'Fable 5.1 — most capable, priciest' },
];
const LEGACY_MODELS: { id: string; label: string }[] = [
  { id: 'claude-fable-5', label: 'Fable 5' },
  { id: 'claude-opus-4-8', label: 'Opus 4.8' },
  { id: 'claude-opus-4-7', label: 'Opus 4.7' },
  { id: 'claude-opus-4-6', label: 'Opus 4.6' },
  { id: 'claude-sonnet-4-6', label: 'Sonnet 4.6' },
  { id: 'claude-sonnet-4-5', label: 'Sonnet 4.5' },
];
const KNOWN_IDS = new Set([...CURRENT_MODELS, ...LEGACY_MODELS].map(m => m.id));
const OTHER = '__other__';
const MODEL_KEY = ['settings', 'model'] as const;
// Tags every write to the model (save AND reset) so each can ask whether
// another is still in flight or queued behind it.
const WRITE_KEY = ['settings-model-write'] as const;

const SOURCE_PILL: Record<ModelStatus['source'], { tone: 'off' | 'info'; label: string; title: string }> = {
  default: { tone: 'off', label: 'Default', title: 'The built-in default model' },
  database: { tone: 'info', label: 'Custom', title: 'Chosen on this page' },
  environment: { tone: 'info', label: 'Environment', title: 'Set by HEADROOM_ANTHROPIC_MODEL on the server' },
};

/**
 * Which Claude model analyzes hat photos.
 *
 * The picker saves the moment it changes. It used to be a select plus a Save
 * button, which left the card in a half-state between the two — the select
 * showing Opus, the server still on Sonnet — and "did that take?" was
 * answered by reloading. The change now applies optimistically (the Claude
 * key card's test result, keyed on the model id, drops at once), and a
 * failed save rolls the picker back to what the server still has.
 */
export function ClaudeModelCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const model = useQuery({ queryKey: MODEL_KEY, queryFn: getModel });
  // Read only to decide whether the post-save check can mean anything. The
  // Claude key card above holds the same query, so this is a cache hit.
  const apiKey = useQuery({ queryKey: ['settings', 'api-key'], queryFn: getApiKeyStatus });

  // "Other…" picked but not saved yet. The select otherwise DERIVES from the
  // server's model id, so a rollback moves it back without extra bookkeeping.
  const [customOpen, setCustomOpen] = useState(false);
  // null = mirror the stored id (an unknown one sits in the custom box).
  const [draft, setDraft] = useState<string | null>(null);
  // The check result, pinned to the model it ran against.
  const [check, setCheck] = useState<{ modelId: string; result: ApiKeyTestResult } | null>(null);

  // After a model change, ask Claude to answer with it. The card used to end
  // with "test the connection above after changing" — a step everyone skips,
  // and a typo'd custom id otherwise surfaces as the next photo failing.
  const checkMut = useMutation({
    mutationFn: async (modelId: string) => ({ modelId, result: await testApiKey() }),
    // Checks are real round trips to Anthropic and can answer out of order:
    // pick Opus, then Haiku a second later, and Opus's answer may land last.
    // Only an answer about the model now in use is kept — otherwise the late
    // one replaced Haiku's result and, being about another model, showed
    // nothing at all.
    onSuccess: r => {
      if (r.modelId === qc.getQueryData<ModelStatus>(MODEL_KEY)?.model_id) setCheck(r);
    },
  });

  // True while another model write is still in flight or queued behind the
  // one asking. A write's own callbacks run while it still counts as pending,
  // hence "more than one".
  const laterWriteQueued = () => qc.isMutating({ mutationKey: WRITE_KEY }) > 1;

  const saveMut = useMutation({
    mutationKey: WRITE_KEY,
    mutationFn: (id: string) => setModel(id),
    // One writer at a time: two quick picks must reach the server in the
    // order they were made, or the earlier one can land last and win.
    scope: { id: 'settings-model' },
    onMutate: async (id: string) => {
      setCheck(null);
      await qc.cancelQueries({ queryKey: MODEL_KEY });
      const prev = qc.getQueryData<ModelStatus>(MODEL_KEY);
      if (prev) qc.setQueryData<ModelStatus>(MODEL_KEY, { ...prev, model_id: id, source: 'database' });
      return { prev };
    },
    onError: (_err, _id, ctx) => {
      // A later pick already owns the cache (its optimistic value); rolling
      // back under it would flash the old model. It rolls back or confirms
      // for itself, and the refetch after the last write settles the truth.
      if (ctx?.prev && !laterWriteQueued()) qc.setQueryData(MODEL_KEY, ctx.prev);
    },
    onSuccess: (data, id) => {
      // Two quick picks (arrow keys on a focused select fire one change per
      // option): the first answering must not write ITS model over the
      // second's optimistic one — the picker flicked back to a model the
      // person had already moved past — nor spend an API call checking it.
      if (laterWriteQueued()) return;
      if (data) qc.setQueryData(MODEL_KEY, data);
      setCustomOpen(false);
      setDraft(null);
      if (apiKey.data?.configured) checkMut.mutate(id);
    },
    // Only the last write refetches: an earlier one's GET could land after
    // the later PUT was sent and before it committed, and show the old model.
    onSettled: () => laterWriteQueued() ? undefined : qc.invalidateQueries({ queryKey: MODEL_KEY }),
  });

  // Not optimistic: with the saved choice cleared the server falls back to
  // HEADROOM_ANTHROPIC_MODEL if that is set, which this page cannot see.
  const resetMut = useMutation({
    mutationKey: WRITE_KEY,
    mutationFn: clearModel,
    scope: { id: 'settings-model' },
    onSuccess: () => {
      setCustomOpen(false);
      setDraft(null);
      setCheck(null);
      toast.success('Model reset to default');
    },
    onSettled: () => laterWriteQueued() ? undefined : qc.invalidateQueries({ queryKey: MODEL_KEY }),
  });

  const status = model.data;
  const current = status?.model_id ?? '';
  const currentKnown = KNOWN_IDS.has(current);
  const showCustom = customOpen || (!!status && !currentKnown);
  const selectValue = showCustom ? OTHER : current;
  const draftValue = draft ?? (currentKnown ? '' : current);
  const customId = draftValue.trim();

  function pick(v: string) {
    if (v === OTHER) {
      setCustomOpen(true);
      setDraft('');
      return;
    }
    setCustomOpen(false);
    setDraft(null);
    if (v !== current) saveMut.mutate(v);
  }

  function saveCustom(e: FormEvent) {
    e.preventDefault();
    if (customId && customId !== current) saveMut.mutate(customId);
  }

  async function reset() {
    const ok = await confirm({
      title: 'Reset to default?',
      body: (
        <p>
          The model chosen here is cleared, and analysis goes back to the
          server&rsquo;s default{status ? <> (<code>{status.default_model_id}</code>)</> : null}.
        </p>
      ),
      confirmLabel: 'Reset to default',
    });
    if (ok) resetMut.mutate();
  }

  const pill = status && (
    <StatusPill tone={SOURCE_PILL[status.source].tone} title={SOURCE_PILL[status.source].title}>
      {SOURCE_PILL[status.source].label}
    </StatusPill>
  );

  const suffix = (id: string) => (id === status?.default_model_id ? ' (default)' : '');

  let checkNote: ReactNode = null;
  if (checkMut.isPending) {
    checkNote = <p className="hr-an-result is-busy" role="status">Checking Claude answers with this model…</p>;
  } else if (check && check.modelId === current) {
    checkNote = check.result.ok
      ? <p className="hr-an-result is-ok" role="status">✓ {check.result.detail}</p>
      : (
        <div className="alert alert-danger small mt-3 mb-0" role="status">
          ✗ {check.result.detail}
        </div>
      );
  }

  return (
    <Panel
      title="Claude model"
      status={pill}
      description="Which Claude model analyzes hat photos. The default suits most collections."
      help={
        <>
          <p>
            Change it if you want more capability (Opus) or lower cost (Haiku).
            A pick saves as soon as you make it and applies to the next analysis;
            with a Claude key set, it is checked against the API straight away, so
            an id that isn&rsquo;t reachable shows up here rather than on your next
            photo. Test connection on the Claude API key card re-runs the check.
          </p>
          <p>
            Legacy models still work — they&rsquo;re just superseded. &ldquo;Other&rdquo;
            takes any model id, including models newer than this build.
          </p>
        </>
      }
      footer={status?.source === 'database' ? (
        <button
          type="button"
          className="btn btn-outline-secondary btn-sm"
          onClick={reset}
          disabled={resetMut.isPending}
        >
          {resetMut.isPending ? 'Resetting…' : 'Reset to default'}
        </button>
      ) : undefined}
    >
      {model.isLoading ? (
        <Skeleton lines={2} />
      ) : (
        <>
          <label className="form-label" htmlFor="claude-model">Model</label>
          <select
            id="claude-model"
            className="form-select"
            value={selectValue}
            onChange={e => pick(e.target.value)}
            disabled={!status}
          >
            <optgroup label="Current">
              {CURRENT_MODELS.map(m => (
                <option key={m.id} value={m.id}>{m.label}{suffix(m.id)}</option>
              ))}
            </optgroup>
            <optgroup label="Legacy — still available, superseded">
              {LEGACY_MODELS.map(m => (
                <option key={m.id} value={m.id}>{m.label}{suffix(m.id)}</option>
              ))}
            </optgroup>
            <option value={OTHER}>Other (enter custom ID)…</option>
          </select>

          {showCustom && (
            // The one free-text path keeps an explicit save: saving on every
            // keystroke would send "claude-o", "claude-op"… to the server,
            // and on blur would save half an id when a tap lands elsewhere.
            <form className="hr-field-row mt-2" onSubmit={saveCustom}>
              <input
                type="text"
                aria-label="Custom model ID"
                className="form-control"
                placeholder="claude-…"
                value={draftValue}
                onChange={e => setDraft(e.target.value)}
                autoComplete="off"
                autoCapitalize="off"
                spellCheck={false}
                autoFocus={customOpen}
              />
              <button
                type="submit"
                className="btn btn-primary"
                disabled={!customId || customId === current || saveMut.isPending}
              >
                Save
              </button>
            </form>
          )}

          {status && (
            <div className="hr-an-model-meta">
              <span className="hr-an-model-active">
                Active <code>{status.model_id}</code>
              </span>
              <SaveState status={mutationSaveStatus(saveMut)} savedKey={saveMut.submittedAt} />
            </div>
          )}
          {checkNote}
        </>
      )}
      <ErrorNote of={[model, saveMut, resetMut, checkMut]} className="mt-3" />
    </Panel>
  );
}
