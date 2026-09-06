import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';
import {
  getAnalysisFailures, getAnalysisJob, getAnalysisQueue, reanalyzeAll, retryFailedAnalysis,
} from '../../api/settings';
import { STAGE_SHORT } from '../hats/AnalysisStatus';
import { timeAgo } from '../../lib/format';

/** The hat page's stage labels, lower-cased for mid-sentence use ("· identifying").
 *  Imported rather than restated: a second table had already drifted in casing. */
const STAGE_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(STAGE_SHORT).map(([k, v]) => [k, v.toLowerCase()]),
);

function pct(job: { done: number; total: number }): number {
  return job.total > 0 ? Math.round((job.done / job.total) * 100) : 0;
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
    queryKey: ['admin', 'analysis-job', jobId],
    queryFn: () => getAnalysisJob(jobId),
  });

  if (q.isPending) return <div className="text-secondary small ps-3">Loading run…</div>;
  if (q.error) {
    return (
      <div className="small ps-3" style={{ color: 'var(--neon-pink)' }}>
        {String(q.error)}
      </div>
    );
  }
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
              <Link to={`/hats/${h.id}`}>
                {h.display_id ?? h.label ?? `Hat #${h.id}`}
              </Link>
              <span className="text-secondary"> · {h.analysis_status ?? 'unknown'}</span>
              {h.analysis_error && (
                <div
                  className="font-mono text-muted"
                  style={{ fontSize: '0.7rem', wordBreak: 'break-word' }}
                >
                  {h.analysis_error}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* Stated, never silent: the list is capped and the count above is a real
          COUNT, so a truncated log must not read as the whole story. */}
      {d.still_tagged > d.hats.length && (
        <div className="text-muted" style={{ fontSize: '0.72rem' }}>
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
 * queue at all. The two numbers are deliberately separate — `queued` is the
 * in-memory depth, `pending_count` is what the database says. A backlog with a
 * dead worker is the failure worth seeing, and only the DB number reveals it.
 */
export function AnalysisQueueCard() {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [openJob, setOpenJob] = useState<number | null>(null);

  // Why hats are failing, grouped. Before this the only place a failure was
  // legible was one hat's own page, and the banner there printed generic
  // advice instead of the reason — so an Anthropic billing refusal that took
  // down all 235 hats read everywhere as "add an API key", on a key that was
  // set and valid. Three days.
  const failures = useQuery({
    queryKey: ['admin', 'analysis-failures'],
    queryFn: getAnalysisFailures,
  });

  const queue = useQuery({
    queryKey: ['admin', 'analysis-queue'],
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
  // failures list above is stale the moment either succeeds. It was not being
  // invalidated at all: after "Re-analyze every hat" the card went on listing
  // failures the run had just wiped, for the whole 30s staleTime.
  const afterQueueing = () => {
    qc.invalidateQueries({ queryKey: ['admin', 'analysis-queue'] });
    qc.invalidateQueries({ queryKey: ['admin', 'analysis-failures'] });
    // Sibling key, not covered by the two above. A retry re-tags the hats it
    // queues, so any run log left open is describing a set that just changed.
    qc.invalidateQueries({ queryKey: ['admin', 'analysis-job'] });
    qc.invalidateQueries({ queryKey: ['hats'] });
  };

  const rerun = useMutation({
    mutationFn: () => reanalyzeAll(),
    onSuccess: () => {
      setConfirming(false);
      afterQueueing();
    },
  });

  // One mutation for both retry buttons; `variables` is the group reason (or
  // undefined for "all failed"), which is also how each button knows whether
  // the spinner belongs to it.
  const retry = useMutation({
    mutationFn: (reason: string | undefined) => retryFailedAnalysis(reason),
    onSuccess: afterQueueing,
  });

  const data = queue.data;
  const backlog = data?.pending_count ?? 0;
  const stalled = backlog > 0 && data?.worker_alive === false;

  // Retryable, not failed: a hat whose photo has gone is a failure the card
  // must still show and a retry cannot fix, so summing `hat_count` here would
  // put a number on the button that the button cannot deliver.
  const totalRetryable = (failures.data ?? []).reduce(
    (n, f) => n + f.retryable_count, 0,
  );

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Analysis Queue</div>
        <p className="text-secondary small mb-3">
          Photo analysis runs in the background. This is the backlog, and the way
          to re-run it across your whole collection after a change to how hats
          are identified or priced.
        </p>

        {queue.isLoading && <div className="text-secondary small">Loading…</div>}

        {data?.current_job && (
          <div className="mb-3">
            <div className="d-flex justify-content-between align-items-baseline mb-1">
              <span>Re-analyzing all hats</span>
              <span className="font-mono small">
                {data.current_job.done} / {data.current_job.total}
              </span>
            </div>
            <div className="hr-progress mb-1">
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
            <div className="text-secondary small">
              started {timeAgo(data.current_job.started_at)}
              {data.current_job.failed > 0 && ` · ${data.current_job.failed} failed`}
            </div>
          </div>
        )}

        {data && (
          <>
            <div className="row g-2 mb-3">
              <div className="col-6">
                <div className="hr-metric">
                  <div className="hr-metric-label">Waiting</div>
                  <div className="hr-metric-value font-mono">{backlog}</div>
                </div>
              </div>
              <div className="col-6">
                <div className="hr-metric">
                  <div className="hr-metric-label">Worker</div>
                  <div className="hr-metric-value font-mono">
                    {data.worker_alive ? 'running' : 'stopped'}
                  </div>
                </div>
              </div>
            </div>

            {stalled && (
              <div className="alert alert-warning">
                {backlog} hat{backlog === 1 ? '' : 's'} waiting, but no worker is
                draining the queue. They'll be picked up on the next restart.
              </div>
            )}

            {backlog === 0 && (
              <div className="text-secondary small mb-3">
                Nothing waiting — every hat with a photo has been analyzed.
              </div>
            )}

            {data.pending.length > 0 && (
              <ul className="hr-plain-list mb-3">
                {data.pending.map(h => (
                  <li key={h.id} className="d-flex align-items-center gap-2 mb-1">
                    <span className="hr-analysis-spinner" aria-hidden="true" />
                    <Link to={`/hats/${h.id}`}>
                      {h.display_id ?? h.label ?? `Hat #${h.id}`}
                    </Link>
                    <span className="text-secondary small">
                      {h.stage ? (STAGE_LABELS[h.stage] ?? h.stage) : 'waiting'}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}

        {data && data.recent_jobs.length > 0 && (
          <div className="mb-3">
            <div className="hr-metric-label mb-1">Recent runs</div>
            <ul className="hr-plain-list">
              {data.recent_jobs.map(j => {
                const open = openJob === j.id;
                return (
                  <li key={j.id} className="mb-1">
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
          </div>
        )}

        {/* Failures come BEFORE the re-analyze-everything button on purpose.
            Retrying 21 casualties of a transient overload is the cheap, correct
            repair, and while it was the only button on this card the expensive
            one was the one people reached for. */}
        {(failures.data?.length ?? 0) > 0 && (
          <div className="mb-3">
            <div className="text-secondary small fw-semibold mb-1">
              Why analysis is failing
            </div>
            {failures.data!.map(f => (
              <div
                key={f.reason}
                className={`alert mb-2 small ${f.is_billing ? 'alert-warning' : 'alert-info'}`}
              >
                <div className="fw-semibold">
                  {f.hat_count} hat{f.hat_count === 1 ? '' : 's'}
                  {f.is_billing && ' · your Anthropic ACCOUNT, not your key'}
                </div>
                <div style={{ wordBreak: 'break-word' }}>{f.reason}</div>
                {f.is_billing && (
                  <div className="mt-1">
                    The key is fine. Top up at{' '}
                    <span className="font-mono">console.anthropic.com</span>{' '}
                    → Plans &amp; Billing, then retry below.
                  </div>
                )}
                <div className="text-muted" style={{ fontSize: '0.72rem' }}>
                  e.g. hat{f.sample_hat_ids.length === 1 ? '' : 's'}{' '}
                  {f.sample_hat_ids.map(id => `#${id}`).join(', ')}
                </div>

                {f.retryable_count > 0 ? (
                  <>
                    <button
                      type="button"
                      className="btn btn-outline-primary btn-sm mt-2"
                      disabled={retry.isPending}
                      onClick={() => retry.mutate(f.reason)}
                    >
                      {retry.isPending && retry.variables === f.reason
                        ? 'Queueing…'
                        : `Retry ${f.retryable_count} hat${f.retryable_count === 1 ? '' : 's'}`}
                    </button>
                    {f.retryable_count < f.hat_count && (
                      <div className="text-muted mt-1" style={{ fontSize: '0.72rem' }}>
                        {f.hat_count - f.retryable_count} of these{' '}
                        {f.hat_count - f.retryable_count === 1 ? 'has' : 'have'} no
                        photo left to analyze and can&rsquo;t be retried.
                      </div>
                    )}
                  </>
                ) : (
                  <div className="text-muted mt-2" style={{ fontSize: '0.72rem' }}>
                    Nothing to retry — no photo left to analyze.
                  </div>
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
                  : `Retry all ${totalRetryable} failed hats`}
              </button>
            )}

          </div>
        )}

        {/* Outside the failures block on purpose. A successful retry clears the
            failures it just queued, so the list empties and unmounts — and a
            banner nested inside it would disappear in the same render, leaving
            the press with no acknowledgment at all. */}
        {retry.data && (
          <div className="alert alert-success mb-3 small">
            {retry.data.queued > 0
              ? `Queued ${retry.data.queued} hat${retry.data.queued === 1 ? '' : 's'} to retry.`
              : 'Nothing left to retry — those hats are already queued.'}
          </div>
        )}
        {retry.error && (
          <div className="alert alert-danger mb-3 small">{String(retry.error)}</div>
        )}

        <hr />

        {/* The checkbox that used to sit here ("Leave hand-entered prices
            alone", ON by default) mapped to a filter for Claude-priced hats.
            It spared nothing — a Manual price is protected unconditionally —
            and after 2.27 moved most hats onto the retail table it silently
            cut the run to a fraction, under a button reading "Re-analyze
            every hat". */}
        <p className="text-secondary small mb-2">
          Covers every hat with a photo. Prices you entered by hand are kept —
          nothing here can overwrite them.
        </p>

        {!confirming ? (
          <button
            type="button"
            className="btn btn-outline-primary w-100"
            onClick={() => setConfirming(true)}
          >Re-analyze every hat</button>
        ) : (
          <div className="alert alert-warning mb-0">
            <div className="mb-2">
              This re-runs Claude for every hat with a photo — minutes of work,
              and it costs an API call each. Background removal is skipped, so
              your cutouts are not touched.
            </div>
            <div className="d-flex gap-2">
              <button
                type="button"
                className="btn btn-primary"
                disabled={rerun.isPending}
                onClick={() => rerun.mutate()}
              >{rerun.isPending ? 'Queueing…' : 'Yes, re-analyze'}</button>
              <button
                type="button"
                className="btn btn-outline-secondary"
                onClick={() => setConfirming(false)}
              >Cancel</button>
            </div>
          </div>
        )}

        {rerun.data && (
          <div className="alert alert-success mt-3 mb-0">
            Queued {rerun.data.queued} hat{rerun.data.queued === 1 ? '' : 's'}.
          </div>
        )}
        {rerun.error && (
          <div className="alert alert-danger mt-3 mb-0">{String(rerun.error)}</div>
        )}
      </div>
    </div>
  );
}
