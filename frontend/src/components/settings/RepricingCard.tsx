import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getRepricing, runRepricing } from '../../api/settings';
import { invalidateHatViews } from '../../lib/invalidate';

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
  const status = useQuery({ queryKey: ['admin', 'repricing'], queryFn: getRepricing });

  const run = useMutation({
    mutationFn: runRepricing,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'repricing'] });
      // Prices changed underneath every hat view. Hand-rolling ['hats']/['hat']
      // here missed the case, room and valuation keys that carry hat data —
      // CLAUDE.md names this helper as the single place that knows them all.
      invalidateHatViews(qc);
    },
  });

  const s = status.data;

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

        <button
          type="button"
          className="btn btn-outline-primary btn-sm"
          onClick={() => run.mutate()}
          disabled={run.isPending}
        >
          {run.isPending ? 'Re-pricing…' : 'Re-price now'}
        </button>
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
