import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../../api/client';

interface PurchaseRow {
  id: number; order_ref: string | null; order_date: string | null;
  item_title: string; price: number | null; hat_id: number | null;
}

export function PurchasesCard() {
  const qc = useQueryClient();
  const purchases = useQuery({
    queryKey: ['admin', 'purchases'],
    queryFn: () => apiFetch<PurchaseRow[]>('/api/admin/purchases'),
  });

  const rematchMut = useMutation({
    mutationFn: () => apiFetch<{ matched: number; unmatched: number }>(
      '/api/admin/purchases/match', { method: 'POST' },
    ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'purchases'] });
      qc.invalidateQueries({ queryKey: ['hats'] });
    },
  });

  const rows = purchases.data ?? [];
  const linked = rows.filter(r => r.hat_id != null).length;

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Purchase History</div>
        <p className="text-secondary small mb-3">
          Order line items imported from your Melin emails. Matched purchases set a
          hat's colorway and cost basis (what you actually paid).
        </p>
        <div className="d-flex gap-2 align-items-center flex-wrap mb-2">
          <span className="text-secondary small font-mono">
            {rows.length} purchases · {linked} linked to hats
          </span>
          {rows.length > 0 && (
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              onClick={() => rematchMut.mutate()}
              disabled={rematchMut.isPending}
            >
              Re-run matching
            </button>
          )}
        </div>
        {rematchMut.data && (
          <div className="small text-secondary mb-2">
            ✓ matched {rematchMut.data.matched}, {rematchMut.data.unmatched} still unmatched
          </div>
        )}
        {rows.slice(0, 8).map(r => (
          <div key={r.id} className="small d-flex justify-content-between gap-2 mb-1">
            <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {r.hat_id != null ? '🔗 ' : '· '}{r.item_title}
            </span>
            <span className="font-mono text-secondary">
              {r.price != null ? `$${r.price.toFixed(2)}` : '—'}
            </span>
          </div>
        ))}
        {rows.length > 8 && <div className="small text-muted">…and {rows.length - 8} more</div>}
      </div>
    </div>
  );
}
