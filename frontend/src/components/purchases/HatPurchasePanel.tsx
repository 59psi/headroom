import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { purchasesForHat } from '../../api/purchases';
import { Panel } from '../ui/Panel';
import { ErrorNote } from '../common/ErrorNote';
import { qk } from '../../lib/queryKeys';
import { useHatLabels } from '../../lib/labels';
import type { HatRead } from '../../types';
import { LinkPurchaseDialog } from './LinkPurchaseDialog';
import { receiptLine, suspectWhy } from './receipt';
import { useKeepLink, useUnlinkPurchase } from './usePurchaseLinks';

/**
 * The order this hat came from, on the hat's own page — and the place to
 * say which one it was when the matcher could not. Linking fills in what you
 * paid, when, and the colorway, but only where the hat has none.
 */
export function HatPurchasePanel({ hat }: { hat: HatRead }) {
  const labels = useHatLabels();
  const [picking, setPicking] = useState(false);
  const purchases = useQuery({
    queryKey: qk.admin.hatPurchases(hat.id),
    queryFn: () => purchasesForHat(hat.id),
  });
  // A suspect link's Unlink is the review list's: it asks, then clears what
  // the link copied onto this hat (see `useUnlinkPurchase`).
  const { unlink, mutation: unlinking } = useUnlinkPurchase();
  const keep = useKeepLink();

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
      <ErrorNote of={[purchases, unlinking, keep]} className="mb-2" />
      {purchases.isSuccess && (linked.length === 0 ? (
        <p className="text-secondary small mb-0">
          No purchase linked
          {likely > 0 && <> — {likely === 1 ? 'one on record fits' : `${likely} on record fit`} this hat</>}.
        </p>
      ) : (
        <ul className="hr-rows is-stacked">
          {linked.map(p => (
            <li key={p.id}>
              <span className="hr-row-text">
                {p.item_title}
                <span className="hr-row-sub">{receiptLine(p, labels.size)}</span>
                {p.suspect && (
                  <span className="hr-row-sub hr-pick-warn small">
                    Earlier matching linked this, and the current rules disagree.{' '}
                    {suspectWhy(p, labels.size)} Check it.
                  </span>
                )}
              </span>
              <span className="hr-row-aside">
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
                  disabled={unlinking.isPending}
                  onClick={() => void unlink(p)}
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
