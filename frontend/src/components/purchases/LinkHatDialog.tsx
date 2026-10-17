import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { hatsForPurchase, linkPurchase } from '../../api/purchases';
import { Modal } from '../common/Modal';
import { ErrorNote } from '../common/ErrorNote';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';
import { qk } from '../../lib/queryKeys';
import { invalidateHatViews, invalidatePurchaseDerived } from '../../lib/invalidate';
import { useHatLabels } from '../../lib/labels';
import { hatName } from '../../lib/placement';
import { tileSrc } from '../../lib/photo';
import { formatDateOnly } from '../../lib/dates';
import { money } from '../../lib/valuation';
import type { HatOption, PurchaseRead } from '../../types';
import { LinkConfirm, PickList, type PickRow } from './PickList';

/** One receipt line, as the dialogs headline it: date · price · size. */
export function receiptLine(p: PurchaseRead, sizeLabel: (v: string) => string): string {
  return [
    p.order_date && formatDateOnly(p.order_date),
    p.price != null && money(p.price),
    p.size && sizeLabel(p.size),
    p.order_ref && `order ${p.order_ref}`,
  ].filter(Boolean).join(' · ');
}

/**
 * "Which hat is this?" — link one purchase to the hat you choose.
 *
 * Every hat is offered, best fit first, each with its photo: the matcher's
 * rules decide the order and never the membership, because the cases it
 * cannot settle (fifteen `Trenches Hydro` hats with nothing on record to tell
 * them apart) are exactly why you are choosing.
 */
export function LinkHatDialog({ purchase, onClose }: { purchase: PurchaseRead; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
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
  const colorwayDiffers = !!(chosen && purchase.colorway && chosen.colorway
    && purchase.colorway.toLowerCase() !== chosen.colorway.toLowerCase());

  const link = useMutation({
    mutationFn: (hat: HatOption) => linkPurchase(purchase.id, {
      hat_id: hat.hat_id,
      replace: takenByOther,
      receipt_colorway: colorwayDiffers && useReceiptColorway,
    }),
    onSuccess: (result, hat) => {
      toast.success(`Linked to ${hatName(hat)}`);
      invalidatePurchaseDerived(qc);
      void invalidateHatViews(qc, result.hat_id);
      if (result.moved_from_hat_id != null) void invalidateHatViews(qc, result.moved_from_hat_id);
      onClose();
    },
  });

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
        onClick={() => link.mutate(chosen)}
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
