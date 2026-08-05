import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../../api/client';

export function ColorwayCatalogCard() {
  const qc = useQueryClient();
  const models = useQuery({
    queryKey: ['meta', 'colorways', 'models'],
    queryFn: () => apiFetch<{ value: string }[]>('/api/meta/colorways'),
  });

  const refreshMut = useMutation({
    mutationFn: () => apiFetch<{ titles_seen: number; new_entries: number; catalog_total: number }>(
      '/api/admin/colorways/refresh', { method: 'POST' },
    ),
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
            {refreshMut.isPending ? 'Harvesting… (takes ~a minute)' : 'Refresh from Melin Recap'}
          </button>
          <span className="text-secondary small font-mono">
            {models.data?.length ?? 0} models known
          </span>
        </div>
        {refreshMut.data && (
          <div className="alert alert-success small mt-3 mb-0">
            ✓ Swept {refreshMut.data.titles_seen} live listings — {refreshMut.data.new_entries} new
            entries, {refreshMut.data.catalog_total} total in catalog.
          </div>
        )}
        {refreshMut.error && (
          <div className="alert alert-danger small mt-3 mb-0">{String(refreshMut.error)}</div>
        )}
      </div>
    </div>
  );
}
