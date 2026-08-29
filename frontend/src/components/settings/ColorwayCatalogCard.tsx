import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getColorwayStatus, refreshColorwayCatalog } from '../../api/settings';
import { SweepProgressBar } from '../common/SweepProgressBar';

export function ColorwayCatalogCard() {
  const qc = useQueryClient();
  const [startedAt, setStartedAt] = useState<number | null>(null);
  // The catalog's real size. This used to read `len(GET /api/meta/colorways)`,
  // which is the AUTOCOMPLETE feed and caps at its own default limit — so the
  // figure sat at 25 no matter how many models had actually been harvested,
  // and looked exactly like a harvest that had only found 25.
  const status = useQuery({
    queryKey: ['admin', 'colorway-status'],
    queryFn: getColorwayStatus,
    refetchInterval: (q) => {
      if (q.state.data?.progress?.running) return 2000;
      // Grace window. The endpoint answers 202 and the harvest starts as a
      // BackgroundTask AFTER the response, so `running` is briefly false right
      // after a start — without this the poll would give up before the sweep it
      // just kicked off ever appeared, and the card would look dead again.
      if (startedAt && Date.now() - startedAt < 30_000) return 2000;
      return false;
    },
  });

  const refreshMut = useMutation({
    // 202: the harvest is minutes of sequential external calls and now runs
    // in the background, so this returns as soon as it has started rather than
    // holding the connection open past whatever proxy sits in front of us.
    mutationFn: () => refreshColorwayCatalog(),
    onSuccess: () => {
      setStartedAt(Date.now());
      qc.invalidateQueries({ queryKey: ['meta', 'colorways'] });
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
            disabled={refreshMut.isPending}
          >
            {refreshMut.isPending ? 'Starting…' : 'Refresh from Melin Recap'}
          </button>
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
              refreshMut.isSuccess
                ? 'Harvest finished — the counts above are current.'
                : undefined
            }
          />
        </div>
        {refreshMut.error && (
          <div className="alert alert-danger small mt-3 mb-0">{String(refreshMut.error)}</div>
        )}
      </div>
    </div>
  );
}
