import { useEffect, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getRepricing, runRepricing, runRepricingAll } from '../../api/settings';
import { invalidateHatViews } from '../../lib/invalidate';
import { SweepProgressBar } from '../common/SweepProgressBar';

/**
 * Periodic re-pricing.
 *
 * Appraisals used to move only when a hat was ANALYZED, so on a real
 * collection every value sat frozen at the date of the last bulk re-analysis —
 * and an expired Anthropic balance stopped prices as well as identification,
 * though pricing never needed Claude at all.
 *
 * The card exists because a list of prices cannot distinguish "nothing
 * changed" from "nothing ran", and only the second is a problem.
 */
export function RepricingCard() {
  const qc = useQueryClient();
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const status = useQuery({
    queryKey: ['admin', 'repricing'],
    queryFn: getRepricing,
    // Poll only while a sweep is actually in flight, so an idle Settings page
    // isn't hitting the API forever. The scheduled sweep runs at boot and for
    // minutes afterwards, and this is the only way to see it happening — the
    // fields below it describe the last run that FINISHED.
    refetchInterval: (q) => {
      if (q.state.data?.progress?.running) return 2000;
      // Grace window, the same one the colorway card needs and for the same
      // reason. `reprice_once` does not call `progress.begin()` until it has
      // taken the sweep lock and run its query, so a status fetch issued the
      // instant the button is pressed still answers `running: false` — the
      // interval would then return false and polling would stop for the whole
      // blocking run, which is precisely when the bar is wanted.
      if (startedAt && Date.now() - startedAt < 20_000) return 2000;
      return false;
    },
  });

  const runAll = useMutation({
    mutationFn: runRepricingAll,
    onSuccess: result => {
      // Only opens the polling window when a sweep actually started; a refused
      // press (one already running) must not restart the grace timer.
      if (result.started) setStartedAt(Date.now());
      qc.invalidateQueries({ queryKey: ['admin', 'repricing'] });
    },
  });

  const run = useMutation({
    mutationFn: runRepricing,
    onMutate: () => {
      // Opens the grace window above. A single invalidate here is not enough
      // on its own: it races the POST and resolves `running: false`.
      setStartedAt(Date.now());
      qc.invalidateQueries({ queryKey: ['admin', 'repricing'] });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'repricing'] });
      // A SIBLING key, not covered by the one above: a sweep rewrites the very
      // (price, source) pairs the shared-price report groups on, so leaving it
      // alone left that card asserting a grouping this run just replaced.
      qc.invalidateQueries({ queryKey: ['admin', 'shared-prices'] });
      // Prices changed underneath every hat view. Hand-rolling ['hats']/['hat']
      // here missed the case, room and valuation keys that carry hat data —
      // CLAUDE.md names this helper as the single place that knows them all.
      invalidateHatViews(qc);
    },
  });

  const s = status.data;

  // A background sweep is in flight. Derived from the SERVER's progress record
  // rather than from mutation state, so it stays true across a reload and
  // however the sweep was started — the scheduled one counts too.
  const sweeping = s?.progress?.running ?? false;

  // A background sweep answers 202 long before any price changes, so the
  // mutation's onSuccess is the wrong place to refresh hat data. Invalidate on
  // the true -> false edge instead, which is the moment the work is actually
  // done and is also reached when the SCHEDULED sweep finishes under us.
  const wasSweeping = useRef(false);
  useEffect(() => {
    if (wasSweeping.current && !sweeping) {
      qc.invalidateQueries({ queryKey: ['admin', 'shared-prices'] });
      invalidateHatViews(qc);
    }
    wasSweeping.current = sweeping;
  }, [sweeping, qc]);

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Re-pricing</div>
        <p className="text-secondary small mb-3">
          Refreshes resale values from the marketplace on a schedule. Independent of
          photo analysis — a median is looked up from details already on the hat, so
          it needs no Claude call and keeps working when analysis can&rsquo;t.
          Prices you entered yourself are never touched.
        </p>

        <SweepProgressBar progress={s?.progress} />

        {s && (
          <div className="hr-metric mb-3">
            <div className="hr-metric-label">
              {s.enabled
                ? `Every ${s.interval_hours} hours`
                : 'Scheduled sweeps off — run one below'}
            </div>
            <div className="hr-metric-value font-mono">
              {s.last_success_at
                ? `${s.last_repriced} of ${s.last_considered} changed`
                : 'No sweep yet'}
            </div>
            {s.last_success_at && (
              <div className="text-secondary small">
                Last swept {new Date(s.last_success_at).toLocaleString()}
              </div>
            )}
            {s.last_error && (
              <div className="text-muted small font-mono" style={{ fontSize: '0.72rem' }}>
                {s.last_error}
              </div>
            )}
          </div>
        )}

        <div className="d-flex gap-2 flex-wrap">
          <button
            type="button"
            className="btn btn-outline-primary btn-sm"
            onClick={() => run.mutate()}
            disabled={run.isPending || sweeping}
          >
            {run.isPending ? 'Re-pricing…' : 'Re-price now'}
          </button>
          {/* Two buttons because they answer different questions: "fix these
              few now, and tell me the number" versus "go do the whole shelf".
              The first is bounded and inline; uncapped it is a multi-minute
              request that a proxy times out, discarding the result. The second
              runs in the background and reports through the progress bar. */}
          <button
            type="button"
            className="btn btn-outline-secondary btn-sm"
            onClick={() => runAll.mutate()}
            disabled={runAll.isPending || sweeping || run.isPending}
          >
            {sweeping ? 'Sweeping…' : 'Re-price all'}
          </button>
        </div>
        {runAll.data?.already_running && (
          <p className="text-secondary small mb-0 mt-2">
            A sweep is already running — watch the bar above.
          </p>
        )}
        {runAll.isError && (
          <p className="small mb-0 mt-2" style={{ color: 'var(--neon-pink)' }}>
            {(runAll.error as Error).message}
          </p>
        )}
        {run.isSuccess && (
          <p className="text-secondary small mb-0 mt-2">
            {run.data.repriced} of {run.data.considered} hats changed price.
            {run.data.remaining > run.data.considered && (
              <> {run.data.remaining} still to sweep &mdash; press again to continue.</>
            )}
          </p>
        )}
        {run.isError && (
          <p className="small mb-0 mt-2" style={{ color: 'var(--neon-pink)' }}>
            {(run.error as Error).message}
          </p>
        )}
      </div>
    </div>
  );
}
