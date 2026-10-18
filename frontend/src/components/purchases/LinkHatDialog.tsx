import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { hatsForPurchase } from '../../api/purchases';
import { Modal } from '../common/Modal';
import { ErrorNote } from '../common/ErrorNote';
import { Skeleton } from '../ui/Skeleton';
import { qk } from '../../lib/queryKeys';
import { useHatLabels } from '../../lib/labels';
import { hatName } from '../../lib/placement';
import { tileSrc } from '../../lib/photo';
import type { PurchaseRead } from '../../types';
import { LinkConfirm, PickList, type PickRow } from './PickList';
import { receiptLine } from './receipt';
import { useLinkPurchase } from './usePurchaseLinks';

/**
 * "Which hat is this?" — link one purchase to the hat you choose.
 *
 * Every hat is offered, best fit first, each with its photo: the matcher's
 * rules decide the order and never the membership, because the cases it
 * cannot settle (fifteen `Trenches Hydro` hats with nothing on record to tell
 * them apart) are exactly why you are choosing.
 */
export function LinkHatDialog({ purchase, onClose }: { purchase: PurchaseRead; onClose: () => void }) {
  const labels = useHatLabels();
  const [chosenId, setChosenId] = useState<number | null>(null);
  const [useReceiptColorway, setUseReceiptColorway] = useState(false);
  const options = useQuery({
    queryKey: qk.admin.purchaseHats(purchase.id),
    queryFn: () => hatsForPurchase(purchase.id),
  });
  const chosen = options.data?.options.find(o => o.hat_id === chosenId) ?? null;
  const takenByOther = chosen != null
    && chosen.linked_purchase_id != null && chosen.linked_purchase_id !== purchase.id;
  // Different by the server's own "same name" rule (`agrees`), not a
  // lowercase compare that called "Black/Gum" and "black gum" two colorways.
  const colorwayDiffers = !!(chosen && purchase.colorway && chosen.colorway
    && !chosen.agrees.includes('colorway'));
  const link = useLinkPurchase(onClose);

  const rows: PickRow[] = (options.data?.options ?? []).map(o => ({
    id: o.hat_id,
    title: o.display_id ? `${o.display_id} · ${o.model_name ?? 'Hat'}` : hatName(o),
    detail: [o.artist_series, o.colorway, o.size && labels.size(o.size)].filter(Boolean).join(' · ')
      || 'No series or colorway on record',
    note: o.linked_purchase_id === purchase.id
      ? 'Linked to this purchase now'
      : o.linked_purchase_id != null ? 'Has another purchase — choosing it replaces that one' : null,
    thumb: o.photo_path || o.thumb_path ? tileSrc(o) : null,
    fits: o.fits,
    agrees: o.agrees,
    search: [o.display_id, o.model_name, o.artist_series, o.colorway, o.construction].filter(Boolean).join(' '),
  }));

  const footer = chosen ? (
    <>
      <button type="button" className="btn btn-outline-secondary" onClick={() => setChosenId(null)}>
        Back
      </button>
      <button
        type="button"
        className="btn btn-primary"
        disabled={link.isPending}
        onClick={() => link.mutate({
          purchaseId: purchase.id,
          link: {
            hat_id: chosen.hat_id,
            replace: takenByOther,
            receipt_colorway: colorwayDiffers && useReceiptColorway,
          },
          done: `Linked to ${hatName(chosen)}`,
        })}
      >
        {link.isPending ? 'Linking…' : `Link to ${hatName(chosen)}`}
      </button>
    </>
  ) : (
    <button type="button" className="btn btn-outline-secondary" onClick={onClose}>Cancel</button>
  );

  return (
    <Modal title="Which hat is this?" onClose={onClose} footer={footer}>
      <div className="hr-pick-receipt">
        <div className="hr-pick-title">{purchase.item_title}</div>
        <div className="hr-pick-detail">{receiptLine(purchase, labels.size)}</div>
      </div>
      <ErrorNote of={[options, link]} className="mb-2" />
      {options.isLoading && <Skeleton height={160} />}
      {chosen ? (
        <LinkConfirm
          thumb={chosen.photo_path || chosen.thumb_path ? tileSrc(chosen) : null}
          heading={hatName(chosen)}
          lines={[
            [chosen.model_name, chosen.artist_series].filter(Boolean).join(' · '),
            chosen.colorway ? `Colorway: ${chosen.colorway}` : 'No colorway on record — the receipt’s fills it in',
          ].filter(Boolean)}
          warnings={takenByOther ? ['This hat already has a purchase linked. Linking replaces it, and undoes what that one filled in.'] : []}
          colorway={colorwayDiffers && purchase.colorway && chosen.colorway ? {
            receipt: purchase.colorway,
            hat: chosen.colorway,
            checked: useReceiptColorway,
            onChange: setUseReceiptColorway,
          } : undefined}
        />
      ) : (
        options.isSuccess && <PickList rows={rows} label="Search your hats" onPick={setChosenId} />
      )}
    </Modal>
  );
}
