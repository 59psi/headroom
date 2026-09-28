import { useEffect, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getRepricing, runRepricing, runRepricingAll } from '../../api/settings';
import type { RepricingStatus } from '../../types';
import { ErrorNote } from '../common/ErrorNote';
import { plural } from '../../lib/format';
import { invalidateHatViews } from '../../lib/invalidate';
import { qk } from '../../lib/queryKeys';
import { SweepProgressBar } from '../common/SweepProgressBar';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';

/**
 * The card's state in one word.
 *
 * Order matters: a sweep in flight outranks everything (it is the live
 * answer), and a FAILING schedule outranks "Scheduled" — `consecutive_failures`
 * is the scheduler's own alarm, which a manual run deliberately does not
 * clear, so a dead background loop cannot hide behind one good button press.
 * A sweep that finished but could not reach the marketplace for some hats is
 * a partial outage, not a quiet market, and says so.
 */
function statusPill(s: RepricingStatus) {
  if (s.progress?.running) return <StatusPill tone="busy">Sweeping</StatusPill>;
  if (s.consecutive_failures > 0) {
    return <StatusPill tone="error" title={s.last_error ?? undefined}>Failing</StatusPill>;
  }
  if (s.last_unreachable > 0) {
    return (
      <StatusPill tone="warn" title={`${plural(s.last_unreachable, 'hat')} couldn’t be priced last sweep`}>
        Partial
      </StatusPill>
    );
  }
  if (s.enabled) return <StatusPill tone="ok">Scheduled</StatusPill>;
  return <StatusPill tone="off">Off</StatusPill>;
}

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
  const toast = useToast();
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const status = useQuery({
    queryKey: qk.admin.repricing(),
    queryFn: getRepricing,
    // Poll only while a sweep is actually in flight, so an idle Settings page
    // isn't hitting the API forever. The scheduled sweep runs at boot and for
    // minutes afterwards, and this is the only way to see it happening — the
    // fields below it describe the last run that FINISHED.
    refetchInterval: (q) => {
      if (q.state.data?.progress?.running) return 2000;
      // Grace window. (The colorway card used to carry one too and replaced it
      // with the server's `in_flight`; this one still needs it.) `reprice_once`
      // does not call `progress.begin()` until it has
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
      // press (one already running) must not restart the grace timer — and
      // must not be toasted as a start either. The refusal is said in place.
      if (result.started) {
        setStartedAt(Date.now());
        toast.success('Sweep started');
      }
      qc.invalidateQueries({ queryKey: qk.admin.repricing() });
    },
  });

  const run = useMutation({
    mutationFn: runRepricing,
    onMutate: () => {
      // Opens the grace window above. A single invalidate here is not enough
      // on its own: it races the POST and resolves `running: false`.
      setStartedAt(Date.now());
      qc.invalidateQueries({ queryKey: qk.admin.repricing() });
    },
    onSuccess: () => {
      // The acknowledgment only. The numbers ("12 of 50 changed, 30 still to
      // sweep") stay in the footer, because "press again" is an instruction
      // that must outlive a toast.
      toast.success('Re-price finished');
      qc.invalidateQueries({ queryKey: qk.admin.repricing() });
      // Prices changed underneath every hat view — and under the shared-price
      // report, which groups on the very (price, source) pairs a sweep
      // rewrites. Hand-rolling ['hats']/['hat'] here missed the case, room
      // and valuation keys that carry hat data; the helper is the single
      // place that knows them all, the shared-price report included.
      void invalidateHatViews(qc);
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
    if (wasSweeping.current && !sweeping) void invalidateHatViews(qc);
    wasSweeping.current = sweeping;
  }, [sweeping, qc]);

  return (
    <Panel
      title="Re-pricing"
      status={s && statusPill(s)}
      description="Refreshes resale values from the marketplace on a schedule. Prices you entered yourself are never touched."
      help={
        <>
          <p>
            Independent of photo analysis — a median is looked up from details
            already on the hat, so it needs no Claude call and keeps working when
            analysis can&rsquo;t.
          </p>
          <p>
            <strong>Re-price now</strong> refreshes a bounded batch while you wait
            and tells you how many changed; press it again to continue.{' '}
            <strong>Re-price all</strong> sweeps the whole collection in the
            background and reports through the progress bar here.
          </p>
        </>
      }
      footer={
        <>
          <button
            type="button"
            className="btn btn-primary"
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
            className="btn btn-outline-secondary"
            onClick={() => runAll.mutate()}
            disabled={runAll.isPending || sweeping || run.isPending}
          >
            {sweeping ? 'Sweeping…' : 'Re-price all'}
          </button>
          {runAll.data?.already_running && (
            <p className="hr-sd-foot-note">
              A sweep is already running — watch the bar above.
            </p>
          )}
          {run.isSuccess && (
            <p className="hr-sd-foot-note">
              {run.data.repriced} of {plural(run.data.considered, 'hat')} changed price.
              {/* `remaining` is what is still DUE after this run (2.76.0), not
                  "eligible at all" — so the test is "any left", never a comparison
                  with `considered`. Under the old `remaining > considered` the last
                  page of a bounded sweep (50 swept, 30 due) said nothing and read
                  as finished. */}
              {run.data.remaining > 0 && (
                <> {run.data.remaining} still to sweep &mdash; press again to continue.</>
              )}
            </p>
          )}
          {/* One note for both buttons. Each used to print its own message in
              a hand-colored paragraph as well, under an ErrorNote that was
              already showing the same text — every failure said twice. */}
          <ErrorNote of={[run, runAll]} className="w-100" />
        </>
      }
    >
      <SweepProgressBar progress={s?.progress} />

      {status.isLoading && <Skeleton height={72} />}
      <ErrorNote of={status} what="Could not load re-pricing status" className="mb-0" />

      {s && (
        <>
          <dl className="hr-metric-grid hr-sd-metrics">
            <div className="hr-metric">
              <dt className="hr-metric-label">Schedule</dt>
              <dd className="hr-metric-value">
                {s.enabled ? `Every ${s.interval_hours} hours` : 'Off'}
              </dd>
              {!s.enabled && (
                <dd className="hr-sd-metric-note">Scheduled sweeps off — run one below</dd>
              )}
            </div>
            <div className="hr-metric">
              <dt className="hr-metric-label">Last sweep</dt>
              <dd className="hr-metric-value">
                {s.last_success_at
                  ? `${s.last_repriced} of ${s.last_considered} changed`
                  : 'No sweep yet'}
              </dd>
              {s.last_success_at && (
                <dd className="hr-sd-metric-note">
                  Last swept {new Date(s.last_success_at).toLocaleString()}
                </dd>
              )}
              {/* Without this a sweep that could reach no marketplace read
                  "0 of 235 changed" — a flat market, when it was a dead one. */}
              {s.last_unreachable > 0 && (
                <dd className="hr-sd-metric-note is-warn">
                  {plural(s.last_unreachable, 'hat')} couldn&rsquo;t reach the marketplace
                </dd>
              )}
            </div>
          </dl>
          {s.last_error && (
            <p className="hr-sd-error-line">
              {s.consecutive_failures > 0 && (
                <>Scheduled sweep failed {plural(s.consecutive_failures, 'time')} in a row:{' '}</>
              )}
              <span className="font-mono">{s.last_error}</span>
            </p>
          )}
        </>
      )}
    </Panel>
  );
}
