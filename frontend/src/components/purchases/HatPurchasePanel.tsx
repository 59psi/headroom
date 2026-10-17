import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { confirmPurchaseLink, purchasesForHat, unmatchPurchase } from '../../api/purchases';
import { Panel } from '../ui/Panel';
import { ErrorNote } from '../common/ErrorNote';
import { useToast } from '../ui/Toast';
import { qk } from '../../lib/queryKeys';
import { invalidateHatViews, invalidatePurchaseDerived } from '../../lib/invalidate';
import { useHatLabels } from '../../lib/labels';
import type { HatRead, PurchaseRead } from '../../types';
import { LinkPurchaseDialog } from './LinkPurchaseDialog';
import { receiptLine } from './LinkHatDialog';

/**
 * The order this hat came from, on the hat's own page — and the place to
 * say which one it was when the matcher could not. Linking fills in what you
 * paid, when, and the colorway, but only where the hat has none.
 */
export function HatPurchasePanel({ hat }: { hat: HatRead }) {
  const qc = useQueryClient();
  const toast = useToast();
  const labels = useHatLabels();
  const [picking, setPicking] = useState(false);
  const purchases = useQuery({
    queryKey: qk.admin.hatPurchases(hat.id),
    queryFn: () => purchasesForHat(hat.id),
  });
  // A suspect link's Unlink is the review list's: you have judged the link
  // wrong, so what it copied onto this hat goes too (see the Purchases card).
  const unlink = useMutation({
    mutationFn: (p: PurchaseRead) => unmatchPurchase(p.id, { clearCopied: p.suspect }),
    onSuccess: () => {
      toast.success('Purchase unlinked');
      invalidatePurchaseDerived(qc);
      void invalidateHatViews(qc, hat.id);
    },
  });
  const keep = useMutation({
    mutationFn: confirmPurchaseLink,
    onSuccess: () => {
      toast.success('Kept — it won’t be flagged again');
      invalidatePurchaseDerived(qc);
    },
  });

  const linked = purchases.data?.linked ?? [];
  const likely = (purchases.data?.options ?? []).filter(o => o.fits).length;

  return (
    <Panel
      title="Purchase"
      actions={purchases.isSuccess && (
        <button type="button" className="btn btn-outline-secondary btn-sm" onClick={() => setPicking(true)}>
          {linked.length > 0 ? 'Change…' : 'Link a purchase…'}
        </button>
      )}
    >
      <ErrorNote of={[purchases, unlink, keep]} className="mb-2" />
      {purchases.isSuccess && (linked.length === 0 ? (
        <p className="text-secondary small mb-0">
          No purchase linked
          {likely > 0 && <> — {likely === 1 ? 'one on record fits' : `${likely} on record fit`} this hat</>}.
        </p>
      ) : (
        <ul className="hr-sd-rows is-stacked">
          {linked.map(p => (
            <li key={p.id}>
              <span className="hr-sd-row-text">
                {p.item_title}
                <span className="hr-sd-row-sub">{receiptLine(p, labels.size)}</span>
                {p.suspect && (
                  <span className="hr-sd-row-sub hr-pick-warn small">
                    Earlier matching linked this, and the current rules disagree
                    {hat.artist_series && <> — “{hat.artist_series}” is nowhere on the receipt</>}.
                    Check it.
                  </span>
                )}
              </span>
              <span className="hr-sd-row-aside">
                {p.suspect && (
                  <button
                    type="button"
                    className="btn btn-outline-secondary btn-sm"
                    aria-label={`Keep ${p.item_title} on this hat`}
                    disabled={keep.isPending}
                    onClick={() => keep.mutate(p.id)}
                  >
                    Keep
                  </button>
                )}
                <button
                  type="button"
                  className={`btn btn-sm ${p.suspect ? 'btn-outline-danger' : 'btn-outline-secondary'}`}
                  aria-label={`Unlink ${p.item_title} from this hat`}
                  disabled={unlink.isPending}
                  onClick={() => unlink.mutate(p)}
                >
                  Unlink
                </button>
              </span>
            </li>
          ))}
        </ul>
      ))}
      {picking && <LinkPurchaseDialog hat={hat} onClose={() => setPicking(false)} />}
    </Panel>
  );
}
