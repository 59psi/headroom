import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ErrorNote } from '../common/ErrorNote';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';
import { useConfirm } from '../ui/Dialogs';
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
  /** Card heading, e.g. "Claude API key". */
  title: string;
  /** Query key under `['settings', …]`; also what save/remove invalidate. */
  queryKey: readonly [string, string];
  getStatus: () => Promise<ApiKeyStatus>;
  setKey: (key: string) => Promise<ApiKeyStatus>;
  deleteKey: () => Promise<void>;
  /** `id` of the input — a label needs it, and tests find the field by it. */
  inputId: string;
  placeholder: string;
  /** One sentence under the title: what the key is for. */
  description: ReactNode;
  /** The long explanation — where to get a key, where it lives — folded
   *  behind "How this works". This is the key's documentation; it moved, it
   *  was not cut. */
  help: ReactNode;
  /** Shown above the field when no key is configured. */
  noKeyText: ReactNode;
  /** Title of the remove confirmation, e.g. "Remove API key?". */
  removeConfirm: string;
  /** What removing it changes — the confirmation's body. */
  removeConsequence: ReactNode;
  /**
   * The environment variable that can supply this key instead. Named on the
   * card when that is where the active key comes from, because the card's
   * Remove cannot touch it: DELETE clears the DATABASE value only, so for an
   * environment key it was a button that did nothing and said nothing.
   */
  envVar: string;
  /** The app's core job needs this key (Claude) rather than merely using it
   *  (Vision). Only changes how loudly "Not set" reads. */
  required?: boolean;
  /** Sunset stripe for the key the app is built around. */
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

const SOURCE_LABEL: Record<string, string> = {
  database: 'saved here',
  environment: 'from the environment',
};

export function KeyCard({ provider }: { provider: KeyProviderSpec }) {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const status = useQuery({ queryKey: provider.queryKey, queryFn: provider.getStatus });
  const [draft, setDraft] = useState('');
  // With a key in place the field is folded behind "Replace", so the card at
  // rest is the key it HAS rather than a form asking for another one.
  const [replacing, setReplacing] = useState(false);
  const [testResult, setTestResult] = useState<ApiKeyTestResult | null>(null);
  const resetOn = provider.test?.resetOn;
  useEffect(() => { setTestResult(null); }, [resetOn]);

  const testMut = useMutation({
    mutationFn: () => provider.test!.run(),
    onSuccess: (data) => setTestResult(data),
  });

  const saveMut = useMutation({
    mutationFn: (key: string) => provider.setKey(key),
    onSuccess: (data) => {
      setDraft('');
      setReplacing(false);
      setTestResult(null);
      // The PUT answers with the new status, so the card shows the new masked
      // key at once instead of the old one for a refetch's worth of time.
      if (data) qc.setQueryData(provider.queryKey, data);
      qc.invalidateQueries({ queryKey: provider.queryKey });
      if (!provider.test) {
        toast.success('Key saved');
        return;
      }
      // Test straight after saving. "Saved" alone was the answer to the wrong
      // question: a mistyped or revoked key saves just as happily as a good
      // one, and the first sign was a hat failing analysis minutes later. The
      // outcome goes in ONE toast, and its detail renders in the card either
      // way — the toast only points at it.
      testMut.mutate(undefined, {
        onSuccess: r => {
          if (r.ok) toast.success('Key saved and working');
          else toast.error('Key saved, but the connection test failed');
        },
        onError: () => toast.error('Key saved, but it could not be tested'),
      });
    },
  });

  const deleteMut = useMutation({
    mutationFn: provider.deleteKey,
    onSuccess: () => {
      setTestResult(null);
      setReplacing(false);
      qc.invalidateQueries({ queryKey: provider.queryKey });
      toast.success('Key removed');
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const key = draft.trim();
    if (key && !saveMut.isPending) saveMut.mutate(key);
  }

  async function remove() {
    const ok = await confirm({
      title: provider.removeConfirm,
      // The consequence is only the whole story when nothing stands behind
      // the saved key. The resolver reads the database first and the
      // environment second, so removing a saved key hands over to an
      // environment one if the server has it — which this card cannot see
      // while the saved key is the active one.
      body: (
        <>
          {provider.removeConsequence}
          <p>
            If <code>{provider.envVar}</code> is set on the server, that key
            takes over instead.
          </p>
        </>
      ),
      confirmLabel: 'Remove key',
      tone: 'danger',
    });
    if (ok) deleteMut.mutate();
  }

  const data = status.data;
  const configured = data?.configured ?? false;
  const source = data?.source ?? null;
  const sourceText = source ? (SOURCE_LABEL[source] ?? source) : null;

  // State, in one word, from what the card actually knows. Nothing while
  // loading: a pill that said "Not set" for the first 200ms would be the
  // exact wrong-answer flash the loading guard below exists to prevent. And
  // "Connected" only once a test has passed — a configured key is not yet a
  // working one.
  let pill: ReactNode = null;
  const pillTitle = sourceText ? `Active key, ${sourceText}` : undefined;
  if (status.isSuccess && data) {
    if (!configured) {
      pill = <StatusPill tone={provider.required ? 'warn' : 'off'}>Not set</StatusPill>;
    } else if (testMut.isPending) {
      pill = <StatusPill tone="busy">Testing…</StatusPill>;
    } else if (testResult) {
      pill = testResult.ok
        ? <StatusPill tone="ok" title={pillTitle}>Connected</StatusPill>
        : <StatusPill tone="error">Test failed</StatusPill>;
    } else {
      pill = <StatusPill tone="ok" title={pillTitle}>Configured</StatusPill>;
    }
  }

  const showForm = !configured || replacing;

  const form = showForm && (
    <form onSubmit={submit} className="hr-an-key-form">
      <label className="form-label" htmlFor={provider.inputId}>
        {configured ? 'Replacement key' : 'API key'}
      </label>
      <div className="hr-field-row">
        <input
          id={provider.inputId}
          type="password"
          className="form-control"
          placeholder={provider.placeholder}
          value={draft}
          onChange={e => setDraft(e.target.value)}
          autoComplete="off"
          spellCheck={false}
          // Only when the person asked for the field: on a phone, focusing it
          // on page load would throw the keyboard over the whole card.
          autoFocus={replacing}
        />
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!draft.trim() || saveMut.isPending}
        >
          {saveMut.isPending ? 'Saving…' : 'Save'}
        </button>
      </div>
      <ErrorNote of={saveMut} className="mt-2" />
    </form>
  );

  let body: ReactNode;
  // Without this the card would briefly claim "No key configured" to someone
  // who has one — the page used to hold a single spinner over every card.
  if (status.isLoading) {
    body = <Skeleton height={64} />;
  } else if (configured && data) {
    body = (
      <>
        <div className="hr-an-key">
          <div className="hr-an-key-value">
            <span className="hr-metric-label">
              Active key{sourceText && <> · {sourceText}</>}
            </span>
            <code className="hr-an-key-masked">{data.masked}</code>
          </div>
          <div className="hr-an-key-actions">
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
              className="btn btn-outline-secondary btn-sm"
              aria-expanded={replacing}
              onClick={() => { setReplacing(r => !r); setDraft(''); saveMut.reset(); }}
            >
              {replacing ? 'Cancel' : 'Replace'}
            </button>
            {source === 'database' && (
              <button
                type="button"
                className="btn btn-outline-danger btn-sm"
                onClick={remove}
                disabled={deleteMut.isPending}
              >
                {deleteMut.isPending ? 'Removing…' : 'Remove key'}
              </button>
            )}
          </div>
        </div>

        {source === 'environment' && (
          <p className="hr-an-note mt-3">
            Set by <code>{provider.envVar}</code> on the server. A key saved here
            takes precedence; to remove that one, unset the variable.
          </p>
        )}

        {testResult && (
          testResult.ok ? (
            <p className="hr-an-result is-ok" role="status">✓ {testResult.detail}</p>
          ) : (
            <div className="alert alert-danger small mt-3 mb-0" role="status">
              ✗ {testResult.detail}
            </div>
          )
        )}
        <ErrorNote of={[testMut, deleteMut]} className="mt-3" />
        {form && <div className="hr-panel-divider" />}
        {form}
      </>
    );
  } else {
    body = (
      <>
        {status.isSuccess
          ? <p className="hr-an-note mb-3">{provider.noKeyText}</p>
          : <ErrorNote of={status} what="Could not read this key's status" className="mb-3" />}
        {form}
      </>
    );
  }

  return (
    <Panel
      title={provider.title}
      status={pill}
      description={provider.description}
      help={provider.help}
      featured={provider.featured}
      className="hr-an-keycard"
    >
      {body}
    </Panel>
  );
}
