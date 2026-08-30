import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { auditFrozenPrices, releaseFrozenPrices } from '../../api/settings';
import { invalidateHatViews } from '../../lib/invalidate';

/**
 * Release prices that a bug marked as "yours".
 *
 * Until 2.57.0 the Edit Hat form resent both price fields on every save,
 * seeded from the loaded hat — and `update_hat` reads a sent key as "a person
 * typed this", which stamps the price `manual` permanently. So editing a
 * colorway froze a scraped melinrecap median as "Price you entered", immune to
 * every future analysis. The number never changed; only its meaning did.
 *
 * 2.57.0 fixed the write path and could not repair what was already written.
 * Nothing records which stamps came from a person, so this previews and lets
 * you choose rather than guessing in a backfill.
 */
export function FrozenPricesCard() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ['admin', 'frozen-prices'],
    queryFn: auditFrozenPrices,
  });
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [done, setDone] = useState<number | null>(null);

  const release = useMutation({
    mutationFn: () => releaseFrozenPrices([...selected], false),
    onSuccess: result => {
      setDone(result.released);
      setSelected(new Set());
      invalidateHatViews(qc);
      qc.invalidateQueries({ queryKey: ['admin', 'frozen-prices'] });
      // Releasing a `manual` scope makes those hats newly ELIGIBLE for the
      // shared-price report, which excludes manual prices — so this mutation
      // can only ever add rows there, and never told it.
      qc.invalidateQueries({ queryKey: ['admin', 'shared-prices'] });
    },
  });

  const rows = data ?? [];
  const toggle = (id: number) =>
    setSelected(prev => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Frozen prices</div>

        {isLoading && <p className="text-muted small mb-0">Checking…</p>}

        {!isLoading && rows.length === 0 && (
          <p className="text-muted small mb-0">
            No hat is holding a price that analysis can't update. Nothing to do.
          </p>
        )}

        {rows.length > 0 && (
          <>
            <p className="text-secondary small">
              These carry a price marked <strong>yours</strong>, so pricing and
              re-analysis leave them alone forever. Until 2.57.0 the Edit form
              stamped that on any save, so a hat you only renamed can be here.
              Releasing keeps the number and lets the next analysis replace it.
            </p>
            <ul className="list-unstyled mb-2">
              {rows.map(r => (
                <li key={r.hat_id} className="d-flex align-items-center gap-2 mb-1">
                  <input
                    type="checkbox"
                    id={`frozen-${r.hat_id}`}
                    aria-label={`Release hat ${r.hat_id}`}
                    checked={selected.has(r.hat_id)}
                    onChange={() => toggle(r.hat_id)}
                  />
                  <label htmlFor={`frozen-${r.hat_id}`} className="small mb-0">
                    <span className="font-mono">#{r.hat_id}</span>{' '}
                    {r.model_name || 'Unidentified'}
                    {r.resale_price != null && <> · resale ${r.resale_price}</>}
                    {r.was_market_priced && (
                      <span className="text-warning"> · was market-priced</span>
                    )}
                  </label>
                </li>
              ))}
            </ul>

            <div className="d-flex align-items-center gap-2">
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                onClick={() => setSelected(new Set(rows.map(r => r.hat_id)))}
              >
                Select all
              </button>
              <button
                type="button"
                className="btn btn-outline-primary btn-sm"
                disabled={selected.size === 0 || release.isPending}
                onClick={() => release.mutate()}
              >
                {release.isPending
                  ? 'Releasing…'
                  : `Release ${selected.size || ''}`.trim()}
              </button>
              {done !== null && (
                <span className="text-muted small">{done} released</span>
              )}
              {release.isError && (
                <span className="text-danger small">Couldn't release — try again</span>
              )}
            </div>
            <p className="text-muted mb-0" style={{ fontSize: '0.72rem', marginTop: 8 }}>
              <strong>was market-priced</strong> means the hat has a melinrecap
              listing on record underneath the manual stamp — the fingerprint of
              the bug rather than of you typing a number.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
