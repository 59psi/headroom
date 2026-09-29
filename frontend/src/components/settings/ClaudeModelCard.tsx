import { useState, type FormEvent, type ReactNode } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getModel, setModel, clearModel, getModelOptions, getApiKeyStatus, testApiKey,
} from '../../api/settings';
import { mk, qk } from '../../lib/queryKeys';
import { formatDateOnly } from '../../lib/dates';
import { timeAgo } from '../../lib/format';
import { ErrorNote } from '../common/ErrorNote';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { SaveState, mutationSaveStatus } from '../ui/SaveState';
import { useToast } from '../ui/Toast';
import { useConfirm } from '../ui/Dialogs';
import type { ApiKeyTestResult, ModelCostLevel, ModelOption, ModelStatus } from '../../types';

// Which models to offer comes from the server (`GET /api/settings/models`):
// this build's catalog — names, relative speed and cost, what supersedes
// what — checked against Anthropic's Models API for the configured key. It
// was two arrays in this file, which could only be as current as the last
// release, and nothing on the card could tell a model Anthropic had retired
// from one that works: an install still saved on one saw a normal-looking
// card, and the next photo failing was the first sign. The server holds the
// one catalog (the analysis reads its forced-tool table too), and the live
// listing is what notices a retirement between releases.
const OTHER = '__other__';
const MODEL_KEY = qk.settings.model();
const MODELS_KEY = qk.settings.models();
// Tags every write to the model (save AND reset) so each can ask whether
// another is still in flight or queued behind it.
const WRITE_KEY = mk.modelWrite();

const SOURCE_PILL: Record<ModelStatus['source'], { tone: 'off' | 'info'; label: string; title: string }> = {
  default: { tone: 'off', label: 'Default', title: 'The built-in default model' },
  database: { tone: 'info', label: 'Custom', title: 'Chosen on this page' },
  environment: { tone: 'info', label: 'Environment', title: 'Set by HEADROOM_ANTHROPIC_MODEL on the server' },
};

/** "Claude Sonnet 5.5" → "Sonnet 5.5". Every option is a Claude model, and
 *  at 390 px the word is a sixth of the select's closed face. */
function shortName(name: string): string {
  return name.replace(/^Claude\s+/, '');
}

/**
 * An id without the suffixes that name one model twice: the date stamp
 * (`claude-haiku-4-5-20251001`), `-latest`, and the `-0` of
 * `claude-opus-4-0`. The list carries ONE entry per model, and an install
 * saved whichever spelling the picker offered at the time — this card's own
 * previous list offered Haiku 4.5 by its dated id. The server shows an entry
 * under the spelling this install saved, so an exact match is the usual case;
 * this covers the moments the two disagree (a list fetched before the last
 * save landed), where the install would otherwise open on "Other…" with the
 * id in a box, as if the setting had broken.
 */
function baseId(id: string): string {
  return id.replace(/-\d{8}$/, '').replace(/-(?:latest|0)$/, '');
}

/**
 * The list entry an id stands for: the exact id, else the one entry sharing
 * its base. Two entries sharing a base (the two dated Claude 3.5 Sonnets) are
 * different models, so an id matching both by base matches neither.
 */
function entryFor(models: readonly ModelOption[], id: string | null | undefined): ModelOption | undefined {
  if (!id) return undefined;
  const exact = models.find(m => m.id === id);
  if (exact) return exact;
  const base = baseId(id);
  const same = models.filter(m => baseId(m.id) === base);
  return same.length === 1 ? same[0] : undefined;
}

/** "Sonnet 5.5 — fast and inexpensive (default)", "Sonnet 6 — new", "Opus 4.1 (retired)". */
function optionLabel(m: ModelOption, isDefault: boolean): string {
  const name = shortName(m.name);
  let text = name;
  if (m.status === 'new') text = `${name} — new`;
  else if (m.status === 'retired') text = `${name} (retired)`;
  else if (m.summary) text = `${name} — ${m.summary}`;
  return isDefault ? `${text} (default)` : text;
}

/** `$$$$$` with the unlit marks dimmed — relative price per token, not a
 *  number: Anthropic's price list changes and a hardcoded figure rots. Read
 *  out as words, since "dollar dollar" says nothing. */
function CostMeter({ level }: { level: ModelCostLevel }) {
  return (
    <span className="hr-an-cost">
      <span aria-hidden="true">
        <span className="hr-an-cost-on">{'$'.repeat(level)}</span>
        <span className="hr-an-cost-off">{'$'.repeat(5 - level)}</span>
      </span>
      <span className="visually-hidden">relative cost {level} of 5</span>
    </span>
  );
}

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
  // `() =>`, not the bare function: TanStack passes its query context as the
  // first argument, which is `refresh` here — and tsc allows it.
  const options = useQuery({ queryKey: MODELS_KEY, queryFn: () => getModelOptions() });
  // Read only to decide whether the post-save check can mean anything. The
  // Claude key card above holds the same query, so this is a cache hit.
  const apiKey = useQuery({ queryKey: qk.settings.apiKey(), queryFn: getApiKeyStatus });

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

  // Only the last write refetches: an earlier one's GET could land after the
  // later PUT was sent and before it committed, and show the old model. The
  // list goes too — the server shows an entry under the spelling this
  // install saved (the dated Haiku id an older build stored), so its ids
  // follow the saved model — but unawaited: "Saved" waits on the model, not
  // on a list that reads the same either way.
  const settle = () => {
    if (laterWriteQueued()) return undefined;
    void qc.invalidateQueries({ queryKey: MODELS_KEY });
    return qc.invalidateQueries({ queryKey: MODEL_KEY });
  };

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
    onSettled: settle,
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
    onSettled: settle,
  });

  // The server keeps Anthropic's listing for hours (it changes a few times a
  // year); this asks it to look again now — after a retirement notice, or
  // to see a model announced this morning.
  const refreshMut = useMutation({
    mutationFn: () => getModelOptions(true),
    onSuccess: data => qc.setQueryData(MODELS_KEY, data),
  });

  const status = model.data;
  const current = status?.model_id ?? '';
  const list = options.data;
  const models = list?.models ?? [];
  // No list at all — the endpoint failed, not the live check (that degrades
  // inside it to the built-in catalog). The card still works: the saved id
  // sits in the custom box, which takes any id.
  //
  // `errorUpdateCount`, not just `isError`: a refetch of a query with no data
  // puts TanStack back in "pending" and clears the error, so on Try again the
  // failed layout — the box that still saves, and the button just pressed —
  // turned into the first-load skeleton, and focus fell to the page. Once the
  // list has failed, it stays in this layout until a list arrives.
  const listFailed = !list && (options.isError || options.errorUpdateCount > 0);
  // The first fetch, which can be a live call to Anthropic (a cold server
  // cache, up to its timeout). Only the picker waits for it: the saved model,
  // Reset and the post-save check do not need the list, and the card showed
  // them the moment the model loaded before there was a list to wait on.
  const listLoading = !list && !listFailed;
  const saved = status ? entryFor(models, current) : undefined;
  // `!!list`: while it loads, every id is "unknown", and the saved one would
  // flash into the custom box before the picker replaced it.
  const showCustom = customOpen || listFailed || (!!status && !!list && !saved);
  const selectValue = showCustom ? OTHER : (saved?.id ?? '');
  const draftValue = draft ?? (saved ? '' : current);
  const customId = draftValue.trim();
  const defaultEntryId = entryFor(models, status?.default_model_id ?? list?.default_model_id)?.id;

  const currentGroup = [
    ...models.filter(m => m.status === 'current'),
    ...models.filter(m => m.status === 'new'),
  ];
  // A retired model is offered only as the one already saved: listing every
  // retired id invites picking one, and dropping the saved one would leave
  // the picker on "Other…" with no word about why.
  const previousGroup = [
    ...models.filter(m => m.status === 'legacy'),
    ...(saved?.status === 'retired' ? [saved] : []),
  ];

  function pick(v: string) {
    if (v === OTHER) {
      setCustomOpen(true);
      setDraft('');
      return;
    }
    setCustomOpen(false);
    setDraft(null);
    // `saved.id` too: a dated id saved by an older build sits on its
    // canonical entry, and re-picking that entry is not a change.
    if (v !== current && v !== saved?.id) saveMut.mutate(v);
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

  // "Connected" only once Claude has answered with THIS model — the same rule
  // the key card follows — and "Failing" when it refused. Until a check has
  // run, the pill says where the choice came from, which is all it knows.
  // The source moves to the tooltip rather than being lost.
  const checked = check && status && check.modelId === status.model_id ? check.result : null;
  const source = status ? SOURCE_PILL[status.source] : null;
  let pill: ReactNode = null;
  if (status && source) {
    pill = checked
      ? (
        <StatusPill tone={checked.ok ? 'ok' : 'error'} title={`${source.label}: ${source.title}`}>
          {checked.ok ? 'Connected' : 'Failing'}
        </StatusPill>
      )
      : <StatusPill tone={source.tone} title={source.title}>{source.label}</StatusPill>;
  }

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

  // The saved model's standing, in the card body — a toast would be gone
  // before anyone read it, and this is true for as long as it stays saved.
  // Each offers the move in one tap and never makes it: a model change
  // changes cost and results, so it is the owner's call.
  let notice: ReactNode = null;
  if (saved) {
    const retired = saved.status === 'retired';
    const gone = retired || saved.available === false;
    // Only a model this key can use is worth a tap: offering a move from one
    // unreachable model to another just trades one failure for the next.
    const usable = (id: string | null | undefined) => {
      const e = entryFor(models, id);
      return e && e.id !== saved.id && e.available !== false ? e : undefined;
    };
    const successor = usable(saved.successor);
    // A model that is gone and has no usable successor (a current model this
    // key cannot reach) still gets a way out: the default. A superseded one
    // that still works does not — "the current version" is the whole offer.
    const offer = gone ? successor ?? usable(defaultEntryId) : successor;
    const switchButton = offer && (
      <button
        type="button"
        className={`btn btn-sm ${gone ? 'btn-primary' : 'btn-outline-secondary'}`}
        onClick={() => pick(offer.id)}
        disabled={saveMut.isPending}
      >
        Switch to {offer.name}
      </button>
    );
    if (gone) {
      // Two different facts, worded apart. A retirement is this build's
      // catalog speaking, true with no key at all — "to this key" there named
      // a key that did not exist. Missing from the live list is about the key
      // in use, and may never have been offered to it, so not "no longer".
      notice = (
        <div className="alert alert-danger small hr-an-model-notice">
          <p>
            {retired
              ? <>Anthropic has retired {saved.name} — analyses with it will fail.</>
              : <>Anthropic doesn&rsquo;t offer {saved.name} to this key — analyses will fail.</>}
          </p>
          {switchButton}
        </div>
      );
    } else if (saved.status === 'legacy' && offer) {
      notice = (
        <div className="alert alert-info small hr-an-model-notice">
          <p>{offer.name} is the current version of this model.</p>
          {switchButton}
        </div>
      );
    }
  }

  // What the model in the picker is like. Nothing for a custom id: this card
  // knows nothing about it, and a blank beats a guess.
  const shown = showCustom ? undefined : saved;
  const about = shown && (shown.speed || shown.cost_level || shown.note || shown.retires_after) ? (
    <div className="hr-an-model-about">
      {(shown.speed || shown.cost_level) && (
        <dl className="hr-an-model-facts">
          {shown.speed && (
            <div>
              <dt>Speed</dt>
              <dd>{shown.speed}</dd>
            </div>
          )}
          {shown.cost_level && (
            <div>
              <dt>Cost</dt>
              <dd><CostMeter level={shown.cost_level} /></dd>
            </div>
          )}
        </dl>
      )}
      {shown.note && <p className="hr-an-note">{shown.note}</p>}
      {shown.retires_after && (
        <p className="hr-an-model-retire">Retires after {formatDateOnly(shown.retires_after)}</p>
      )}
    </div>
  ) : null;

  // Where the list came from: Anthropic's own listing for this key, or the
  // catalog built into this release (and why). "Available" means something
  // only in the first case, so the reader needs to know which this is.
  let provenance: ReactNode = null;
  if (list) {
    let text: string;
    if (list.live) {
      text = list.checked_at ? `Checked with Anthropic ${timeAgo(list.checked_at)}` : 'Checked with Anthropic';
    } else {
      text = list.live_error ? `Built-in list — ${list.live_error}` : 'Built-in list';
    }
    provenance = (
      <div className="hr-an-model-source">
        <span className="hr-an-fine">{text}</span>
        <button
          type="button"
          className="btn btn-outline-secondary btn-sm"
          onClick={() => refreshMut.mutate()}
          disabled={refreshMut.isPending}
        >
          {refreshMut.isPending
            ? 'Refreshing…'
            : <>Refresh{' '}<span className="visually-hidden">model list</span></>}
        </button>
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
          {/* Not "more speed (Haiku)": Haiku 4.5 measured no faster than
              Sonnet 5.5 on real hats, and cannot cache this prompt. What
              each model is like is under the picker, from the catalog. */}
          <p>
            Change it for finer identification (Opus) or the most capable model
            (Fable), at a higher price per hat; each model&rsquo;s speed and
            relative cost show under the picker.
            A pick saves as soon as you make it and applies to the next analysis;
            with a Claude key set, it is checked against the API straight away, so
            an id that isn&rsquo;t reachable shows up here rather than on your next
            photo. Test connection on the Claude API key card re-runs the check.
          </p>
          <p>
            With a key set, the list is checked against Anthropic&rsquo;s own model
            listing for that key — every few hours, or now with Refresh — so a model
            Anthropic has retired is flagged here, with a one-tap move to its
            successor. Nothing is switched for you. Previous-generation models
            still work; they&rsquo;re just superseded. &ldquo;Other&rdquo; takes any
            model id, including models newer than this build.
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
          {listLoading ? (
            // The picker's shape — its caption over a select-height bar — so
            // the card settles once when the list lands, not by a control's
            // height. The caption is not a <label>: there is nothing to name.
            <>
              <div className="form-label" aria-hidden="true">Model</div>
              <Skeleton height={44} label="Loading the model list…" />
            </>
          ) : listFailed ? (
            <>
              <div className="hr-an-model-listfail">
                <ErrorNote of={options} what="The model list couldn’t load" className="" />
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  onClick={() => options.refetch()}
                  disabled={options.isFetching}
                >
                  {options.isFetching ? 'Trying…' : 'Try again'}
                </button>
              </div>
              <label className="form-label" htmlFor="claude-model-custom">Model ID</label>
            </>
          ) : (
            <>
              <label className="form-label" htmlFor="claude-model">Model</label>
              <select
                id="claude-model"
                className="form-select hr-an-model-select"
                value={selectValue}
                onChange={e => pick(e.target.value)}
                disabled={!status}
              >
                <optgroup label="Current models">
                  {currentGroup.map(m => (
                    <option key={m.id} value={m.id}>{optionLabel(m, m.id === defaultEntryId)}</option>
                  ))}
                </optgroup>
                {previousGroup.length > 0 && (
                  <optgroup label="Previous generation">
                    {previousGroup.map(m => (
                      <option key={m.id} value={m.id}>{optionLabel(m, m.id === defaultEntryId)}</option>
                    ))}
                  </optgroup>
                )}
                <option value={OTHER}>Other (enter custom ID)…</option>
              </select>
            </>
          )}

          {showCustom && (
            // The one free-text path keeps an explicit save: saving on every
            // keystroke would send "claude-o", "claude-op"… to the server,
            // and on blur would save half an id when a tap lands elsewhere.
            <form className={`hr-field-row${listFailed ? '' : ' mt-2'}`} onSubmit={saveCustom}>
              <input
                id="claude-model-custom"
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

          {notice}
          {about}

          {status && (
            <div className="hr-an-model-meta">
              <span className="hr-an-model-active">
                Active <code>{status.model_id}</code>
              </span>
              <SaveState status={mutationSaveStatus(saveMut)} savedKey={saveMut.submittedAt} />
            </div>
          )}
          {checkNote}
          {provenance}
        </>
      )}
      <ErrorNote of={[model, saveMut, resetMut, checkMut, refreshMut]} className="mt-3" />
    </Panel>
  );
}
