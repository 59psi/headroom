import { useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getColorwayStatus, refreshColorwayCatalog } from '../../api/settings';
import { SweepProgressBar } from '../common/SweepProgressBar';
import { ErrorNote } from '../common/ErrorNote';

export function ColorwayCatalogCard() {
  const qc = useQueryClient();
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
  const inFlight = status.data?.in_flight ?? false;

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
      // finished" for somebody else's run.
      if (res.already_running) return;
      qc.invalidateQueries({ queryKey: ['admin', 'colorway-status'] });
    },
  });

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Colorway Catalog</div>
        <p className="text-secondary small mb-3">
          Model + colorway names harvested from Melin Recap's live listings —
          includes sold-out drops that are long gone from melin.com. Powers the
          autocomplete on the Edit Hat form and purchase matching.
        </p>
        <div className="d-flex gap-2 align-items-center flex-wrap">
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
              Already running — watch the progress below.
            </span>
          )}
          <span className="text-secondary small font-mono">
            {status.data
              ? `${status.data.models} models · ${status.data.colorways} colorways · ${status.data.entries} listings`
              : '—'}
          </span>
        </div>
        <div className="mt-3">
          <SweepProgressBar
            progress={status.data?.progress}
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
        <ErrorNote of={[status, refreshMut]} className="mt-3" />
      </div>
    </div>
  );
}
