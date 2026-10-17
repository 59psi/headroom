import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { purchasesForHat, unmatchPurchase } from '../../api/purchases';
import { Panel } from '../ui/Panel';
import { ErrorNote } from '../common/ErrorNote';
import { useToast } from '../ui/Toast';
import { qk } from '../../lib/queryKeys';
import { invalidateHatViews, invalidatePurchaseDerived } from '../../lib/invalidate';
import { useHatLabels } from '../../lib/labels';
import type { HatRead } from '../../types';
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
  const unlink = useMutation({
    mutationFn: (purchaseId: number) => unmatchPurchase(purchaseId),
    onSuccess: () => {
      toast.success('Purchase unlinked');
      invalidatePurchaseDerived(qc);
      void invalidateHatViews(qc, hat.id);
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
      <ErrorNote of={[purchases, unlink]} className="mb-2" />
      {purchases.isSuccess && (linked.length === 0 ? (
        <p className="text-secondary small mb-0">
          No purchase linked
          {likely > 0 && <> — {likely === 1 ? 'one on record fits' : `${likely} on record fit`} this hat</>}.
        </p>
      ) : (
        <ul className="hr-sd-rows">
          {linked.map(p => (
            <li key={p.id}>
              <span className="hr-sd-row-text">
                {p.item_title}
                <span className="hr-sd-row-sub">{receiptLine(p, labels.size)}</span>
              </span>
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                aria-label={`Unlink ${p.item_title} from this hat`}
                disabled={unlink.isPending}
                onClick={() => unlink.mutate(p.id)}
              >
                Unlink
              </button>
            </li>
          ))}
        </ul>
      ))}
      {picking && <LinkPurchaseDialog hat={hat} onClose={() => setPicking(false)} />}
    </Panel>
  );
}
