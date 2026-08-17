import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';
import { getAnalysisQueue, reanalyzeAll } from '../../api/settings';

/** Mirrors the stage labels on the hat page. */
const STAGE_LABELS: Record<string, string> = {
  cutout: 'removing background',
  identifying: 'identifying',
  pricing: 'checking prices',
  resale: 'checking resale',
};

/**
 * What the analysis worker is doing, and the button that fills it.
 *
 * Before this the queue was invisible: a hat showed "Analyzing…" with no way to
 * tell whether twenty were ahead of it, or whether anything was draining the
 * queue at all. The two numbers are deliberately separate — `queued` is the
 * in-memory depth, `pending_count` is what the database says. A backlog with a
 * dead worker is the failure worth seeing, and only the DB number reveals it.
 */
function pct(job: { done: number; total: number }): number {
  return job.total > 0 ? Math.round((job.done / job.total) * 100) : 0;
}

/** Coarse relative time — a job list wants "4m ago", not a timestamp. */
function since(iso: string): string {
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return 'just now';
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86_400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86_400)}d ago`;
}

export function AnalysisQueueCard() {
  const qc = useQueryClient();
  const [sparePrices, setSparePrices] = useState(true);
  const [confirming, setConfirming] = useState(false);

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

  const rerun = useMutation({
    mutationFn: () => reanalyzeAll(sparePrices),
    onSuccess: () => {
      setConfirming(false);
      qc.invalidateQueries({ queryKey: ['admin', 'analysis-queue'] });
      qc.invalidateQueries({ queryKey: ['hats'] });
    },
  });

  const data = queue.data;
  const backlog = data?.pending_count ?? 0;
  const stalled = backlog > 0 && data?.worker_alive === false;

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
              <span>Re-analysing all hats</span>
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
              started {since(data.current_job.started_at)}
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
                Nothing waiting — every hat with a photo has been analysed.
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
              {data.recent_jobs.map(j => (
                <li key={j.id} className="text-secondary small">
                  {j.status === 'running' ? 'running' : since(j.finished_at ?? j.started_at)}
                  {' · '}{j.done}/{j.total}
                  {j.failed > 0 && ` · ${j.failed} failed`}
                </li>
              ))}
            </ul>
          </div>
        )}

        <hr />

        <label className="d-flex align-items-center gap-2 mb-2" style={{ cursor: 'pointer' }}>
          <input
            type="checkbox"
            aria-label="Leave hand-entered prices alone"
            checked={sparePrices}
            onChange={e => setSparePrices(e.target.checked)}
            style={{ width: 20, height: 20, flexShrink: 0 }}
          />
          <span>
            Leave hand-entered prices alone
            <span className="text-secondary small d-block">
              Only re-analyse hats whose price came from Claude
            </span>
          </span>
        </label>

        {!confirming ? (
          <button
            type="button"
            className="btn btn-outline-primary w-100"
            onClick={() => setConfirming(true)}
          >Re-analyse every hat</button>
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
              >{rerun.isPending ? 'Queueing…' : 'Yes, re-analyse'}</button>
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
