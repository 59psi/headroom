import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { linkPurchase, purchasesForHat } from '../../api/purchases';
import { Modal } from '../common/Modal';
import { ErrorNote } from '../common/ErrorNote';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';
import { qk } from '../../lib/queryKeys';
import { invalidateHatViews, invalidatePurchaseDerived } from '../../lib/invalidate';
import { useHatLabels } from '../../lib/labels';
import type { HatRead, PurchaseOption } from '../../types';
import { LinkConfirm, PickList, type PickRow } from './PickList';
import { receiptLine } from './LinkHatDialog';

/**
 * "Which purchase was this hat?" — the same link, chosen from the hat's side.
 * Every hat purchase on record is offered, best fit first; one already on
 * another hat is offered too, flagged, because moving a link the matcher got
 * wrong is the reason this exists.
 */
export function LinkPurchaseDialog({ hat, onClose }: { hat: HatRead; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const labels = useHatLabels();
  const [chosenId, setChosenId] = useState<number | null>(null);
  const [useReceiptColorway, setUseReceiptColorway] = useState(false);
  const options = useQuery({
    queryKey: qk.admin.hatPurchases(hat.id),
    queryFn: () => purchasesForHat(hat.id),
  });
  const current = options.data?.linked[0] ?? null;
  const chosen = options.data?.options.find(o => o.id === chosenId) ?? null;
  const colorwayDiffers = !!(chosen && chosen.colorway && hat.colorway
    && chosen.colorway.toLowerCase() !== hat.colorway.toLowerCase());

  const link = useMutation({
    mutationFn: (purchase: PurchaseOption) => linkPurchase(purchase.id, {
      hat_id: hat.id,
      replace: current != null,
      receipt_colorway: colorwayDiffers && useReceiptColorway,
    }),
    onSuccess: result => {
      toast.success('Purchase linked');
      invalidatePurchaseDerived(qc);
      void invalidateHatViews(qc, hat.id);
      if (result.moved_from_hat_id != null) void invalidateHatViews(qc, result.moved_from_hat_id);
      onClose();
    },
  });

  const rows: PickRow[] = (options.data?.options ?? []).map(p => ({
    id: p.id,
    title: p.item_title,
    detail: receiptLine(p, labels.size) || 'No date or price on the receipt',
    note: p.linked_hat_id != null
      ? `On ${p.linked_hat_display_id ?? 'another hat'} now — choosing it moves it here`
      : null,
    fits: p.fits,
    agrees: p.agrees,
    search: [p.item_title, p.colorway, p.order_ref].filter(Boolean).join(' '),
  }));

  const warnings = chosen ? [
    current && `Replaces “${current.item_title}” as this hat’s purchase, and undoes what it filled in.`,
    chosen.linked_hat_id != null
      && `Moves it off ${chosen.linked_hat_display_id ?? 'the hat it is on'}, undoing what it filled in there.`,
  ].filter((w): w is string => !!w) : [];

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
        {link.isPending ? 'Linking…' : 'Link this purchase'}
      </button>
    </>
  ) : (
    <button type="button" className="btn btn-outline-secondary" onClick={onClose}>Cancel</button>
  );

  return (
    <Modal title="Which purchase was this hat?" onClose={onClose} footer={footer}>
      <ErrorNote of={[options, link]} className="mb-2" />
      {options.isLoading && <Skeleton height={160} />}
      {chosen ? (
        <LinkConfirm
          heading={chosen.item_title}
          lines={[receiptLine(chosen, labels.size)].filter(Boolean)}
          warnings={warnings}
          colorway={colorwayDiffers && chosen.colorway && hat.colorway ? {
            receipt: chosen.colorway,
            hat: hat.colorway,
            checked: useReceiptColorway,
            onChange: setUseReceiptColorway,
          } : undefined}
        />
      ) : (
        options.isSuccess && (rows.length > 0
          ? <PickList rows={rows} label="Search your purchases" onPick={setChosenId} />
          : <p className="text-secondary small mb-0">No hat purchases on record. Import your order history in Settings → Data → Purchase history.</p>)
      )}
    </Modal>
  );
}
