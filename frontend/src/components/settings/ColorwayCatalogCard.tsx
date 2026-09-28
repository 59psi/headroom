import { useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getColorwayStatus, refreshColorwayCatalog } from '../../api/settings';
import type { CatalogStatus } from '../../types';
import { SweepProgressBar } from '../common/SweepProgressBar';
import { ErrorNote } from '../common/ErrorNote';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';

/** One word for the catalog. `in_flight` first: it is true from the moment
 *  the slot is claimed, before `progress.running` catches up. */
function statusPill(s: CatalogStatus) {
  if (s.in_flight) return <StatusPill tone="busy">Harvesting</StatusPill>;
  // The progress record keeps the error after the run stops — that is what
  // makes it readable at all — so a failed last harvest is the state until
  // the next one starts.
  if (s.progress?.error) return <StatusPill tone="error">Failed</StatusPill>;
  if (s.entries === 0) return <StatusPill tone="off">Empty</StatusPill>;
  return <StatusPill tone="ok">Ready</StatusPill>;
}

export function ColorwayCatalogCard() {
  const qc = useQueryClient();
  const toast = useToast();
  // The catalog's real size. This used to read `len(GET /api/meta/colorways)`,
  // which is the AUTOCOMPLETE feed and caps at its own default limit — so the
  // figure sat at 25 no matter how many models had actually been harvested,
  // and looked exactly like a harvest that had only found 25.
  const status = useQuery({
    queryKey: ['admin', 'colorway-status'],
    queryFn: getColorwayStatus,
    // `in_flight`, not `progress.running`. The slot is claimed synchronously
    // in the request and `begin()` runs inside the task, so `running` is still
    // false for a moment after the 202 — this card used to bridge that with a
    // 30-second wall-clock grace window, which is a client-side guess at
    // server state that the server can simply report. The guess was also
    // local: a harvest started from a phone left the laptop's card idle and
    // its button enabled, so the next press was refused with no explanation.
    refetchInterval: (q) => (q.state.data?.in_flight ? 2000 : false),
  });
  const s = status.data;
  const inFlight = s?.in_flight ?? false;

  // The picker's colorway feed changes when the harvest FINISHES, not when
  // the 202 arrives. It used to be invalidated on the 202 — before a single
  // row had been written — so the Edit form kept the pre-harvest catalog
  // until its own staleTime ran out. The true→false edge is also reached
  // when a harvest started from another device finishes under us.
  const wasInFlight = useRef(false);
  useEffect(() => {
    if (wasInFlight.current && !inFlight) {
      qc.invalidateQueries({ queryKey: ['meta', 'colorways'] });
    }
    wasInFlight.current = inFlight;
  }, [inFlight, qc]);

  const refreshMut = useMutation({
    // 202: the harvest is minutes of sequential external calls and now runs
    // in the background, so this returns as soon as it has started rather than
    // holding the connection open past whatever proxy sits in front of us.
    mutationFn: () => refreshColorwayCatalog(),
    onSuccess: res => {
      // `started` false means a harvest was already in flight and this press
      // began nothing. Treating a refusal as a start would show "Harvest
      // finished" for somebody else's run — and toasting it as a start would
      // say the same thing sooner. The refusal is said in place instead.
      if (res.already_running) return;
      toast.success('Harvest started');
      qc.invalidateQueries({ queryKey: ['admin', 'colorway-status'] });
    },
  });

  return (
    <Panel
      title="Colorway catalog"
      status={s && statusPill(s)}
      description="Model and colorway names harvested from Melin Recap's live listings, sold-out drops included."
      help={
        <p>
          Includes sold-out drops that are long gone from melin.com. Powers the
          autocomplete on the Edit Hat form and purchase matching. A refresh is
          minutes of lookups, so it runs in the background — progress shows here
          while it works, from whichever device started it.
        </p>
      }
      footer={
        <>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => refreshMut.mutate()}
            disabled={refreshMut.isPending || inFlight}
          >
            {refreshMut.isPending
              ? 'Starting…'
              : inFlight
                ? 'Harvesting…'
                : 'Refresh from Melin Recap'}
          </button>
          {refreshMut.data?.already_running && (
            <span className="text-secondary small">
              Already running — watch the progress above.
            </span>
          )}
          <ErrorNote of={refreshMut} className="w-100" />
        </>
      }
    >
      {status.isLoading && <Skeleton height={72} />}
      <ErrorNote of={status} what="Could not load the catalog" className="mb-0" />
      {s && (
        <dl className="hr-metric-grid hr-sd-metrics">
          <div className="hr-metric">
            <dt className="hr-metric-label">Models</dt>
            <dd className="hr-metric-value">{s.models}</dd>
          </div>
          <div className="hr-metric">
            <dt className="hr-metric-label">Colorways</dt>
            <dd className="hr-metric-value">{s.colorways}</dd>
          </div>
          <div className="hr-metric">
            <dt className="hr-metric-label">Listings</dt>
            <dd className="hr-metric-value">{s.entries}</dd>
          </div>
        </dl>
      )}
      {s?.last_harvest && !inFlight && (
        <p className="hr-sd-legend mt-2 mb-0">
          Last harvest {new Date(s.last_harvest).toLocaleString()}
        </p>
      )}
      <div className="mt-3 hr-sd-progress-slot">
        <SweepProgressBar
          progress={s?.progress}
          idleLabel={
            // `isSuccess` is true for a REFUSAL too — 202 with
            // `already_running` is a successful request that started
            // nothing. Keying the finished message on it announced a harvest
            // this press never began, and would have reported someone else's
            // run as this one's result.
            refreshMut.data?.started
              ? 'Harvest finished — the counts above are current.'
              : undefined
          }
        />
      </div>
    </Panel>
  );
}
