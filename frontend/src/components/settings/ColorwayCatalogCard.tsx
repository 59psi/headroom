import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../../api/client';
import { refreshColorwayCatalog } from '../../api/settings';

export function ColorwayCatalogCard() {
  const qc = useQueryClient();
  const models = useQuery({
    queryKey: ['meta', 'colorways', 'models'],
    queryFn: () => apiFetch<{ value: string }[]>('/api/meta/colorways'),
  });

  const refreshMut = useMutation({
    // 202: the harvest is minutes of sequential external calls and now runs
    // in the background, so this returns as soon as it has started rather than
    // holding the connection open past whatever proxy sits in front of us.
    mutationFn: () => refreshColorwayCatalog(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['meta', 'colorways'] }),
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
            {models.data?.length ?? 0} models known
          </span>
        </div>
        {refreshMut.data && (
          <div className="alert alert-success small mt-3 mb-0">
            ✓ {refreshMut.data.detail} The model count above updates once it lands —
            reload in a minute or two.
          </div>
        )}
        {refreshMut.error && (
          <div className="alert alert-danger small mt-3 mb-0">{String(refreshMut.error)}</div>
        )}
      </div>
    </div>
  );
}
