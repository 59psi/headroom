import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ErrorNote } from '../common/ErrorNote';
import { auditFrozenPrices, releaseFrozenPrices } from '../../api/settings';
import type { FrozenPriceRow } from '../../types';
import { plural } from '../../lib/format';
import { invalidateHatViews } from '../../lib/invalidate';
import { qk } from '../../lib/queryKeys';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';

const KEY = qk.admin.frozenPrices();

const MARKET_PRICED_NOTE =
  'A melinrecap listing is on record underneath the manual stamp — the fingerprint of the bug rather than of you typing a number.';

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
  const toast = useToast();
  const audit = useQuery({
    queryKey: KEY,
    queryFn: auditFrozenPrices,
  });
  const { data, isLoading } = audit;
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const release = useMutation({
    mutationFn: (ids: number[]) => releaseFrozenPrices(ids, false),
    // Optimistic: a released hat is by definition no longer frozen, so it
    // leaves the list the moment it is sent rather than a round trip later.
    // The server's answer is predictable here — it releases exactly the ids it
    // was given — and a failure puts the rows AND the selection back, so a
    // retry is one tap rather than re-ticking the list.
    onMutate: async (ids: number[]) => {
      await qc.cancelQueries({ queryKey: KEY });
      const previous = qc.getQueryData<FrozenPriceRow[]>(KEY);
      qc.setQueryData<FrozenPriceRow[]>(KEY, rows => rows?.filter(r => !ids.includes(r.hat_id)));
      setSelected(new Set());
      return { previous, ids };
    },
    onError: (_err, _ids, ctx) => {
      if (ctx?.previous) qc.setQueryData(KEY, ctx.previous);
      if (ctx) setSelected(new Set(ctx.ids));
    },
    onSuccess: result => {
      toast.success(`Released ${plural(result.released, 'price')}`);
      // Includes the shared-price report: releasing a `manual` scope makes
      // those hats newly ELIGIBLE for it (it excludes manual prices), so this
      // mutation can only ever add rows there — and once never told it.
      void invalidateHatViews(qc);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: KEY });
    },
  });

  const rows = data ?? [];
  const allSelected = rows.length > 0 && rows.every(r => selected.has(r.hat_id));
  const toggle = (id: number) =>
    setSelected(prev => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  return (
    <Panel
      title="Frozen prices"
      status={audit.isSuccess && (rows.length
        ? <StatusPill tone="warn">{plural(rows.length, 'hat')}</StatusPill>
        : <StatusPill tone="ok">Nothing to do</StatusPill>)}
      description="Hats holding a price marked yours, which pricing and re-analysis never update."
      help={
        <>
          <p>
            These carry a price marked <strong>yours</strong>, so pricing and
            re-analysis leave them alone forever. Until 2.57.0 the Edit form
            stamped that on any save, so a hat you only renamed can be here.
            Releasing keeps the number and lets the next analysis replace it.
          </p>
          <p>
            <strong>was market-priced</strong> means the hat has a melinrecap
            listing on record underneath the manual stamp — the fingerprint of
            the bug rather than of you typing a number.
          </p>
        </>
      }
      footer={rows.length > 0 && (
        <>
          <button
            type="button"
            className="btn btn-primary"
            disabled={selected.size === 0 || release.isPending}
            onClick={() => release.mutate([...selected])}
          >
            {release.isPending
              ? 'Releasing…'
              : `Release ${selected.size || ''}`.trim()}
          </button>
          <button
            type="button"
            className="btn btn-outline-secondary"
            onClick={() => setSelected(allSelected ? new Set() : new Set(rows.map(r => r.hat_id)))}
          >
            {allSelected ? 'Select none' : 'Select all'}
          </button>
        </>
      )}
    >
      {isLoading && <Skeleton lines={3} />}
      <ErrorNote of={audit} what="Could not check" />
      {/* Outside the rows branch: a failed release rolls the rows back, but
          a note that only rendered alongside them would still go missing on
          the render where they were optimistically all gone. */}
      <ErrorNote of={release} what="Could not release" className="mb-2" />

      {audit.isSuccess && rows.length === 0 && (
        <p className="text-muted small mb-0">
          No hat is holding a price that analysis can&rsquo;t update. Nothing to do.
        </p>
      )}

      {rows.length > 0 && (
        <ul className="hr-sd-checklist">
          {rows.map(r => (
            <li key={r.hat_id}>
              <input
                type="checkbox"
                className="form-check-input"
                id={`frozen-${r.hat_id}`}
                aria-label={`Release hat ${r.hat_id}`}
                checked={selected.has(r.hat_id)}
                onChange={() => toggle(r.hat_id)}
              />
              <label htmlFor={`frozen-${r.hat_id}`}>
                <span className="font-mono text-secondary">#{r.hat_id}</span>{' '}
                {r.model_name || 'Unidentified'}
                {r.resale_price != null && (
                  <span className="text-secondary"> · resale <span className="font-mono">${r.resale_price}</span></span>
                )}
                {r.was_market_priced && (
                  <span className="text-warning" title={MARKET_PRICED_NOTE}> · was market-priced</span>
                )}
              </label>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
