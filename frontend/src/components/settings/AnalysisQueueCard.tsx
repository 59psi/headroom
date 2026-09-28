import { useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';
import {
  getAnalysisFailures, getAnalysisJob, getAnalysisQueue, reanalyzeAll, retryFailedAnalysis,
} from '../../api/settings';
import { STAGE_SHORT } from '../hats/AnalysisStatus';
import { noun, plural, timeAgo } from '../../lib/format';
import { analysisViewKeys, hatViewKeys, invalidateAll } from '../../lib/invalidate';
import { hatName } from '../../lib/placement';
import { qk } from '../../lib/queryKeys';
import { ErrorNote } from '../common/ErrorNote';
import { Panel } from '../ui/Panel';
import { StatusPill, type PillTone } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';
import { useConfirm } from '../ui/Dialogs';
import type { AnalysisFailureGroup, AnalysisQueueStatus } from '../../types';

/** The hat page's stage labels, lower-cased for mid-sentence use ("· identifying").
 *  Imported rather than restated: a second table had already drifted in casing. */
const STAGE_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(STAGE_SHORT).map(([k, v]) => [k, v.toLowerCase()]),
);

function pct(job: { done: number; total: number }): number {
  return job.total > 0 ? Math.round((job.done / job.total) * 100) : 0;
}

/**
 * Why some (or all) of a group cannot be retried, in words — by the reason
 * the server gives, not a guess.
 *
 * Every non-retryable group used to read "no photo left to analyze". A group
 * of keyless failures read that too, while its photos were all there: the
 * thing standing between them and a retry was a Claude key, and the card was
 * telling the owner to go and find photos.
 */
function unretryableNote(f: AnalysisFailureGroup): string {
  const stuck = f.hat_count - f.retryable_count;
  switch (f.unretryable_reason) {
    case 'no_api_key':
      return 'Add a Claude API key in the Claude API key card — then these can be retried.';
    case 'no_photo':
      return f.retryable_count > 0
        ? `${stuck} of these ${noun(stuck, 'has', 'have')} no photo left to analyze and can’t be retried.`
        : 'Nothing to retry — no photo left to analyze.';
    default:
      return f.retryable_count > 0
        ? `${stuck} of these can’t be retried right now.`
        : 'Nothing to retry right now.';
  }
}

/**
 * The queue's state in one word, for the card's header.
 *
 * Ordered by what matters most: a backlog with a dead worker is the failure
 * worth seeing (nothing happens until a restart), so it outranks a run in
 * flight. "Idle" is only said when the worker is alive AND nothing waits —
 * a stopped worker with an empty queue is still a stopped worker.
 */
function queueState(d: AnalysisQueueStatus): { tone: PillTone; label: string; title?: string } {
  const backlog = d.pending_count;
  if (backlog > 0 && !d.worker_alive) {
    return { tone: 'error', label: 'Stalled', title: `${plural(backlog, 'hat')} waiting, no worker running` };
  }
  if (d.current_job) return { tone: 'busy', label: 'Running', title: 'Re-analyzing all hats' };
  if (backlog > 0) return { tone: 'busy', label: `${backlog} waiting`, title: 'Worker running' };
  if (!d.worker_alive) return { tone: 'warn', label: 'Worker stopped', title: 'Nothing waiting' };
  return { tone: 'ok', label: 'Idle', title: 'Worker running, nothing waiting' };
}

/**
 * What one run actually did, hat by hat.
 *
 * Its own component with its own query so the request only happens when a run
 * is expanded — the card is on a Settings page that already fires plenty, and
 * a run's log is hundreds of rows nobody has asked for until they click.
 */
function RunLog({ jobId }: { jobId: number }) {
  const q = useQuery({
    queryKey: qk.admin.analysisJob(jobId),
    queryFn: () => getAnalysisJob(jobId),
  });

  if (q.isPending) {
    return (
      <div className="hr-run-log">
        <Skeleton lines={3} label="Loading run…" />
      </div>
    );
  }
  if (q.isError) return <ErrorNote of={q} what="Could not load this run" className="hr-an-runlog-error" />;
  const d = q.data;
  if (!d) return null;

  return (
    <div className="hr-run-log">
      <div className="text-secondary small mb-2">
        {/* A run whose hats have all been re-analyzed since is NOT a run that
            did nothing — `analysis_job_id` is one column and later runs take
            ownership of it. Saying so is the difference between an empty list
            that explains itself and one that looks broken. */}
        {d.still_tagged === 0 ? (
          <>Every hat from this run has been re-analyzed since, so none is still
            attributed to it. It covered {d.total} at the time.</>
        ) : (
          <>
            {d.still_tagged} of {d.total} still attributed to this run
            {d.failed_count > 0 && ` · ${d.failed_count} still failing`}
          </>
        )}
      </div>

      {d.hats.length > 0 && (
        <ul className="hr-plain-list">
          {d.hats.map(h => (
            <li key={h.id} className="mb-2 small">
              <Link to={`/hats/${h.id}`}>{hatName(h)}</Link>
              <span className="text-secondary"> · {h.analysis_status ?? 'unknown'}</span>
              {h.analysis_error && (
                <div className="hr-an-verbatim">{h.analysis_error}</div>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* Stated, never silent: the list is capped and the count above is a real
          COUNT, so a truncated log must not read as the whole story. */}
      {d.still_tagged > d.hats.length && (
        <div className="hr-an-fine">
          Showing the first {d.hats.length} of {d.still_tagged}, failures first.
        </div>
      )}
    </div>
  );
}

/**
 * What the analysis worker is doing, and the button that fills it.
 *
 * Before this the queue was invisible: a hat showed "Analyzing…" with no way to
 * tell whether twenty were ahead of it, or whether anything was draining the
 * queue at all. The two facts are deliberately separate — `pending_count` is
 * what the database says is waiting, `worker_alive` is whether anything is
 * draining it. A backlog with a dead worker is the failure worth seeing, and
 * only the pair reveals it; the header pill states it in one word.
 */
export function AnalysisQueueCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const [openJob, setOpenJob] = useState<number | null>(null);

  // Why hats are failing, grouped. Before this the only place a failure was
  // legible was one hat's own page, and the banner there printed generic
  // advice instead of the reason — so an Anthropic billing refusal that took
  // down all 235 hats read everywhere as "add an API key", on a key that was
  // set and valid. Three days.
  const failures = useQuery({
    queryKey: qk.admin.analysisFailures(),
    queryFn: getAnalysisFailures,
  });

  const queue = useQuery({
    queryKey: qk.admin.analysisQueue(),
    queryFn: getAnalysisQueue,
    // Poll only while there is something to watch, so an idle Settings page
    // isn't hitting the API every few seconds forever.
    refetchInterval: (q) => {
      const d = q.state.data;
      // Keep polling while a run is in flight even if the backlog momentarily
      // reads zero — the last hat is still being written.
      return (d?.pending_count ?? 0) > 0 || d?.current_job ? 3000 : false;
    },
  });

  // Both runs move hats to 'pending' and CLEAR their failure text, so the
  // failures list above is stale the moment either succeeds — and so are the
  // recent-errors card, the nav badge and every hat view that shows a status.
  // This used to hand-roll four keys and miss the badge and the hat pages;
  // the recent-errors card's retry of the same operation named them all. Both
  // go through the same two helpers now.
  const afterQueueing = () => {
    void invalidateAll(qc, analysisViewKeys(), hatViewKeys());
  };

  // Acknowledged by toast rather than a banner in the card. A banner here was
  // itself a fix — nested inside the failures list, a successful retry cleared
  // the failures it queued, the list unmounted, and the banner went with it in
  // the same render, leaving the press with no acknowledgment at all. A toast
  // lives outside the card entirely, so no refetch can take it away.
  const rerun = useMutation({
    mutationFn: () => reanalyzeAll(),
    onSuccess: (r) => {
      afterQueueing();
      toast.success(`Queued ${plural(r.queued, 'hat')}.`);
    },
  });

  // One mutation for both retry buttons; `variables` is the group reason (or
  // undefined for "all failed"), which is also how each button knows whether
  // the spinner belongs to it.
  const retry = useMutation({
    mutationFn: (reason: string | undefined) => retryFailedAnalysis(reason),
    onSuccess: (r) => {
      afterQueueing();
      // Pressing twice is the normal way to get a zero: the first press
      // cleared the failures and moved the hats to pending. Reported as its
      // own outcome, because "Queued 0 hats" reads as a silent no-op.
      if (r.queued > 0) toast.success(`Queued ${plural(r.queued, 'hat')} to retry.`);
      else toast.info('Nothing left to retry — those hats are already queued.');
    },
  });

  async function confirmRerun() {
    const ok = await confirm({
      title: 'Re-analyze every hat?',
      body: (
        <>
          <p>
            This re-runs Claude for every hat with a photo — minutes of work,
            and it costs an API call each. Background removal is skipped, so
            your cutouts are not touched.
          </p>
          {/* Both halves are true by construction, not by care: a Manual
              price is never repriced, and a palette the owner edited is
              `colors_source = 'owner'`, which every analysis color write
              (`hat_service.replace_analysis_colors`) leaves alone. */}
          <p>
            Prices you entered by hand and colors you edited are kept. Model
            names and design notes are rewritten from each photo.
          </p>
        </>
      ),
      confirmLabel: 'Yes, re-analyze',
    });
    if (ok) rerun.mutate();
  }

  const data = queue.data;
  const backlog = data?.pending_count ?? 0;
  const stalled = backlog > 0 && data?.worker_alive === false;
  const state = data ? queueState(data) : null;

  // Retryable, not failed: a hat whose photo has gone is a failure the card
  // must still show and a retry cannot fix, so summing `hat_count` here would
  // put a number on the button that the button cannot deliver.
  const totalRetryable = (failures.data ?? []).reduce(
    (n, f) => n + f.retryable_count, 0,
  );

  let queueBody: ReactNode = null;
  if (queue.isLoading) {
    queueBody = <Skeleton lines={2} />;
  } else if (data) {
    queueBody = (
      <>
        {data.current_job && (
          <div className="hr-an-run">
            <div className="hr-an-run-head">
              <span>Re-analyzing all hats</span>
              <span className="font-mono small">
                {data.current_job.done} / {data.current_job.total}
              </span>
            </div>
            <div className="hr-progress">
              <div
                className="hr-progress-fill"
                style={{ width: `${pct(data.current_job)}%` }}
                role="progressbar"
                aria-label="Re-analysis progress"
                aria-valuenow={data.current_job.done}
                aria-valuemin={0}
                aria-valuemax={data.current_job.total}
              />
            </div>
            <div className="text-secondary small mt-1">
              started {timeAgo(data.current_job.started_at)}
              {data.current_job.failed > 0 && ` · ${data.current_job.failed} failed`}
            </div>
          </div>
        )}

        {stalled && (
          <div className="alert alert-warning small mb-3">
            {plural(backlog, 'hat')} waiting, but no worker is
            draining the queue. They&rsquo;ll be picked up on the next restart.
          </div>
        )}

        {backlog === 0 ? (
          <p className="hr-an-note">
            Nothing waiting — every hat with a photo has been analyzed.
          </p>
        ) : (
          <section className="hr-an-group">
            <h3 className="hr-an-subhead">
              Waiting <span className="hr-an-count">{backlog}</span>
            </h3>
            {data.pending.length > 0 && (
              <ul className="hr-plain-list hr-an-pending">
                {data.pending.map(h => (
                  <li key={h.id}>
                    <span className="hr-analysis-spinner" aria-hidden="true" />
                    <Link to={`/hats/${h.id}`}>{hatName(h)}</Link>
                    <span className="text-secondary small">
                      {h.stage ? (STAGE_LABELS[h.stage] ?? h.stage) : 'waiting'}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {data.recent_jobs.length > 0 && (
          <section className="hr-an-group">
            <h3 className="hr-an-subhead">Recent runs</h3>
            <ul className="hr-plain-list">
              {data.recent_jobs.map(j => {
                const open = openJob === j.id;
                return (
                  <li key={j.id}>
                    <button
                      type="button"
                      className="hr-run-row"
                      aria-expanded={open}
                      onClick={() => setOpenJob(open ? null : j.id)}
                    >
                      <span aria-hidden="true" className="hr-run-caret">{open ? '▾' : '▸'}</span>
                      {j.status === 'running' ? 'running' : timeAgo(j.finished_at ?? j.started_at)}
                      {' · '}{j.done}/{j.total}
                      {j.failed > 0 && ` · ${j.failed} failed`}
                    </button>
                    {open && <RunLog jobId={j.id} />}
                  </li>
                );
              })}
            </ul>
          </section>
        )}
      </>
    );
  }

  return (
    <Panel
      title="Analysis queue"
      status={state && <StatusPill tone={state.tone} title={state.title}>{state.label}</StatusPill>}
      description="Photo analysis runs in the background: this is its backlog, and the way to re-run it."
      help={
        <p>
          Hats wait here between upload and a finished analysis. Re-run the whole
          collection after a change to how hats are identified or priced; for
          hats that failed, retry just those from &ldquo;Why analysis is
          failing&rdquo; — it is cheaper, and usually what is needed.
        </p>
      }
      footer={
        <div className="hr-an-rerun">
          {/* The checkbox that used to sit here ("Leave hand-entered prices
              alone", ON by default) mapped to a filter for Claude-priced hats.
              It spared nothing — a Manual price is protected unconditionally —
              and after 2.27 moved most hats onto the retail table it silently
              cut the run to a fraction, under a button reading "Re-analyze
              every hat". */}
          <p className="hr-an-rerun-text">
            Covers every hat with a photo. Prices you entered by hand and colors
            you edited are kept — nothing here can overwrite them.
          </p>
          {/* Outline, not primary, on purpose: see the failures comment below.
              The expensive button is the one people reached for while it was
              the loudest thing on the card. */}
          <button
            type="button"
            className="btn btn-outline-primary"
            disabled={rerun.isPending}
            onClick={confirmRerun}
          >
            {rerun.isPending ? 'Queueing…' : 'Re-analyze every hat'}
          </button>
        </div>
      }
    >
      {/* The queue's own read failing used to render nothing at all — an
          empty card, indistinguishable from one still loading. */}
      <ErrorNote of={queue} what="Could not read the queue" className="mb-3" />
      <ErrorNote of={failures} what="Could not read why analysis is failing" className="mb-3" />
      {queueBody}

      {/* Failures come BEFORE the re-analyze-everything button on purpose.
          Retrying 21 casualties of a transient overload is the cheap, correct
          repair, and while it was the only button on this card the expensive
          one was the one people reached for. */}
      {(failures.data?.length ?? 0) > 0 && (
        <section className="hr-an-group">
          <h3 className="hr-an-subhead">Why analysis is failing</h3>
          {failures.data!.map(f => (
            <div
              key={f.reason}
              className={`hr-an-failure${f.is_billing ? ' is-billing' : ''}`}
            >
              <div className="hr-an-failure-count">
                {plural(f.hat_count, 'hat')}
                {f.is_billing && ' · your Anthropic account, not your key'}
              </div>
              <div className="hr-an-failure-reason">{f.reason}</div>
              {f.is_billing && (
                <div className="hr-an-failure-fix">
                  The key is fine. Top up at{' '}
                  <span className="font-mono">console.anthropic.com</span>{' '}
                  → Plans &amp; Billing, then retry below.
                </div>
              )}
              <div className="hr-an-fine">
                e.g. {noun(f.sample_hat_ids.length, 'hat')}{' '}
                {f.sample_hat_ids.map(id => `#${id}`).join(', ')}
              </div>

              {f.retryable_count > 0 ? (
                <div className="hr-an-failure-actions">
                  <button
                    type="button"
                    className="btn btn-outline-primary btn-sm"
                    disabled={retry.isPending}
                    onClick={() => retry.mutate(f.reason)}
                  >
                    {retry.isPending && retry.variables === f.reason
                      ? 'Queueing…'
                      : `Retry ${plural(f.retryable_count, 'hat')}`}
                  </button>
                  {f.retryable_count < f.hat_count && (
                    <span className="hr-an-fine">{unretryableNote(f)}</span>
                  )}
                </div>
              ) : (
                <div className="hr-an-fine mt-2">{unretryableNote(f)}</div>
              )}
            </div>
          ))}

          {/* Only worth its own button when the per-group ones don't already
              cover everything in one press. */}
          {failures.data!.length > 1 && totalRetryable > 0 && (
            <button
              type="button"
              className="btn btn-outline-primary btn-sm w-100"
              disabled={retry.isPending}
              onClick={() => retry.mutate(undefined)}
            >
              {retry.isPending && retry.variables === undefined
                ? 'Queueing…'
                : `Retry all ${plural(totalRetryable, 'failed hat')}`}
            </button>
          )}
        </section>
      )}

      {/* One note per press, never one shared between them: ErrorNote shows
          the FIRST failure in its list, and a mutation keeps its error until
          it runs again — so a retry refused earlier stood in front of the
          re-analyze that had just been refused, and that one said nothing. */}
      <ErrorNote of={retry} className="mt-3" />
      <ErrorNote of={rerun} className="mt-3" />
    </Panel>
  );
}
