import { useEffect, useRef } from 'react';
import { Link } from 'react-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getRecentErrors, getRecentErrorsCount, getApiKeyStatus } from '../../api/settings';
import { reanalyzeHat } from '../../api/hats';
import { analysisViewKeys, hatViewKeys, invalidateAll } from '../../lib/invalidate';
import { timeAgo } from '../../lib/format';
import { tileSrc } from '../../lib/photo';
import { hatName } from '../../lib/placement';
import { qk } from '../../lib/queryKeys';
import { ErrorNote } from '../common/ErrorNote';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';
import type { RecentError } from '../../types';

const LIMIT = 20;
const ERRORS_KEY = qk.admin.recentErrors();
// The nav badge reads `recentErrorsCount`, which is a sibling key, NOT a
// child — 'recent-errors' does not prefix-match 'recent-errors-count', so
// refreshing the list alone left the badge showing a count the list no
// longer agreed with. Every refresh here names both.
const COUNT_KEY = qk.admin.recentErrorsCount();

/**
 * One failed hat, with a retry that re-runs analysis on its current photo.
 *
 * Its own component so each row owns its request: two rows retried in quick
 * succession each keep their own "Retrying…" and their own error. The row is
 * NOT removed optimistically — with no Claude key the retry runs the local
 * fallback, which can leave a failure reason in place, so whether the hat
 * leaves this list is the server's call. The refetch after success decides.
 */
function ErrorRow({ err }: { err: RecentError }) {
  const qc = useQueryClient();
  const toast = useToast();
  const name = hatName(err);

  const retry = useMutation({
    mutationFn: () => reanalyzeHat(err.hat_id),
    onSuccess: (hat) => {
      // Three outcomes, not two. Queued (a key and a worker) or re-analyzed
      // clean are successes. But an inline run — no Claude key, so the local
      // fallback; or the worker off — can come back still carrying a failure
      // reason, and then the hat stays on this list: "re-analyzed" as a
      // success sat right next to the row's new error.
      if (hat?.analysis_status === 'pending') toast.success(`${name} queued for re-analysis`);
      else if (hat?.analysis_error) toast.info(`${name} re-analyzed, but it is still failing`);
      else toast.success(`${name} re-analyzed`);
      // This list, the badge's count, and the queue card's backlog and
      // failure groups all just changed — the same set the queue card's own
      // retry refreshes, so both name it through one helper — and so did the
      // hat, wherever it is shown.
      void invalidateAll(qc, analysisViewKeys(), hatViewKeys(err.hat_id));
    },
  });

  // Settled for good only when it left the failure state: queued, or run
  // clean. A retry that came back still failing keeps its button — adding a
  // key and pressing again is exactly the next step.
  const settled = retry.isSuccess && (retry.data?.analysis_status === 'pending' || !retry.data?.analysis_error);

  return (
    <li className="hr-an-err">
      <div className="hr-an-err-row">
        <Link to={`/hats/${err.hat_id}`} className="hr-an-err-main">
          {/* The tile derivative, not the full cutout: this is a thumbnail,
              and a page of twenty 1200px PNGs is megabytes for nothing. */}
          {err.photo_path ? (
            <img src={tileSrc(err)} alt="" className="hr-thumb hr-an-err-thumb" />
          ) : (
            <span className="hr-an-err-thumb is-empty" aria-hidden="true" />
          )}
          <span className="hr-an-err-text">
            <span className="hr-an-err-id">{name}</span>
            <span className="hr-an-err-msg" title={err.analysis_error || ''}>
              {err.analysis_error || '(no message)'}
            </span>
            {/* Both, visibly. The exact time used to be the whole label; kept
                only in a hover tooltip it was out of reach on a phone, and no
                other screen shows when a hat was last analyzed. */}
            {err.analyzed_at && (
              <time className="hr-an-err-time" dateTime={err.analyzed_at}>
                {timeAgo(err.analyzed_at)} · {new Date(err.analyzed_at).toLocaleString()}
              </time>
            )}
          </span>
        </Link>
        {/* Only a hat with a photo can be retried: the endpoint answers 400
            without one, and a button that can only fail is worse than none. */}
        {err.photo_path && (
          settled ? (
            <StatusPill tone={retry.data?.analysis_status === 'pending' ? 'busy' : 'info'}>
              {retry.data?.analysis_status === 'pending' ? 'Queued' : 'Retried'}
            </StatusPill>
          ) : (
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              aria-label={`Retry analysis for ${name}`}
              disabled={retry.isPending}
              onClick={() => retry.mutate()}
            >
              {retry.isPending ? 'Retrying…' : 'Retry'}
            </button>
          )
        )}
      </div>
      <ErrorNote of={retry} what={`Could not retry ${name}`} className="mt-2" />
    </li>
  );
}

export function RecentErrorsCard() {
  const qc = useQueryClient();
  const errors = useQuery({ queryKey: ERRORS_KEY, queryFn: () => getRecentErrors(LIMIT) });
  // The real total. The list is capped at LIMIT, so its length alone would
  // top out at 20 and call it the whole story. Shared with the nav badge,
  // which polls it — this is a cache hit, not another request.
  const count = useQuery({ queryKey: COUNT_KEY, queryFn: getRecentErrorsCount });
  const apiKey = useQuery({ queryKey: qk.settings.apiKey(), queryFn: getApiKeyStatus });

  // The count polls (the badge's once a minute); the list does not. When the
  // count MOVES, the list is out of date — refetch it, so the pill above and
  // the rows below never tell two stories ("1 failed" over "No analysis
  // errors.") for as long as the page stays open. Keyed on a change, not on
  // every answer: the first value is the baseline, and an unchanged poll
  // costs nothing. `cancelRefetch: false` leaves a list fetch already under
  // way (a Refresh or a retry just asked for both) to finish instead of
  // restarting it.
  const seenCount = useRef<number | undefined>(undefined);
  const latestCount = count.data?.count;
  useEffect(() => {
    if (latestCount === undefined) return;
    if (seenCount.current !== undefined && seenCount.current !== latestCount) {
      qc.invalidateQueries({ queryKey: ERRORS_KEY }, { cancelRefetch: false });
    }
    seenCount.current = latestCount;
  }, [latestCount, qc]);

  const list = errors.data;
  const total = Math.max(count.data?.count ?? 0, list?.length ?? 0);

  const pill = list && (
    total > 0
      ? <StatusPill tone="error">{total} failed</StatusPill>
      : <StatusPill tone="ok">None</StatusPill>
  );

  return (
    <Panel
      title="Recent analysis errors"
      status={pill}
      actions={
        <button
          type="button"
          className="btn btn-outline-secondary btn-sm"
          onClick={() => {
            qc.invalidateQueries({ queryKey: ERRORS_KEY });
            qc.invalidateQueries({ queryKey: COUNT_KEY });
          }}
          disabled={errors.isFetching}
        >
          {errors.isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      }
      description="Hats whose last analysis failed, newest first."
      help={
        <p>
          Each row opens the hat; Retry re-runs analysis on its current photo
          (background removal is skipped). To retry many at once, grouped by
          cause, use &ldquo;Why analysis is failing&rdquo; in the Analysis queue
          card. The list shows the newest {LIMIT}.
        </p>
      }
    >
      <ErrorNote of={[errors, apiKey]} className="mb-2" />
      {errors.isLoading ? (
        <Skeleton lines={3} />
      ) : list && list.length === 0 ? (
        <p className="hr-an-note">
          No analysis errors.
          {/* Only once the key status is KNOWN: while it loaded, this used to
              tell someone with a key to go and configure one. */}
          {apiKey.data && !apiKey.data.configured && ' Configure a Claude API key to start analyzing.'}
        </p>
      ) : list ? (
        <>
          <ul className="hr-plain-list">
            {list.map(err => <ErrorRow key={err.hat_id} err={err} />)}
          </ul>
          {total > list.length && (
            <p className="hr-an-fine mt-2 mb-0">
              Showing the {list.length} most recent of {total}.
            </p>
          )}
        </>
      ) : null}
    </Panel>
  );
}
