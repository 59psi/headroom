import { useMutation, useQueryClient } from '@tanstack/react-query';
import { confirmPurchaseLink, linkPurchase, unmatchPurchase } from '../../api/purchases';
import { useConfirm } from '../ui/Dialogs';
import { useToast } from '../ui/Toast';
import { qk } from '../../lib/queryKeys';
import { invalidateHatViews, invalidatePurchaseDerived } from '../../lib/invalidate';
import type { PurchaseLink, PurchaseRead } from '../../types';

/**
 * The link actions the Purchase history card and the hat page's Purchase
 * panel share. Each was written twice, once per surface, and the two copies
 * had already drifted: the card asked before nothing, the panel likewise, and
 * only the card updated its list optimistically.
 */

/** "Keep" — you vouch for a link, and it is never listed to check again. */
export function useKeepLink() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: confirmPurchaseLink,
    onSuccess: () => {
      toast.success('Kept — it won’t be flagged again');
      invalidatePurchaseDerived(qc);
    },
  });
}

/**
 * Unlink one purchase — the undo a single wrong link needs.
 *
 * A SUSPECT link's Unlink is a rejection: you have looked at the hat and the
 * receipt and said the link was wrong, so the colorway, price and date it
 * copied go too, even on links too old to have recorded their writes
 * (`clearCopied`). That is a write onto the hat, so it asks first; a plain
 * Unlink only reverts what the link recorded writing, and does not.
 *
 * Optimistic on the Purchase history list: the row drops its link the
 * instant it is confirmed, and a failure restores the cached list. Where
 * that list is not cached (the hat page, before Settings was opened) the
 * update is a no-op.
 */
export function useUnlinkPurchase() {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const key = qk.admin.purchases();
  const mutation = useMutation({
    mutationFn: (p: PurchaseRead) => unmatchPurchase(p.id, { clearCopied: p.suspect }),
    onMutate: async p => {
      await qc.cancelQueries({ queryKey: key });
      const previous = qc.getQueryData<PurchaseRead[]>(key);
      qc.setQueryData<PurchaseRead[]>(key, list =>
        list?.map(r => (r.id === p.id ? { ...r, hat_id: null, hat: null, suspect: false, suspect_reason: null } : r)));
      return { previous };
    },
    onError: (_err, _p, ctx) => {
      if (ctx?.previous) qc.setQueryData(key, ctx.previous);
    },
    onSuccess: (result, p) => {
      toast.success('Purchase unlinked');
      void invalidateHatViews(qc, result.hat_id ?? p.hat_id ?? undefined);
    },
    // The list refetches on failure too — the rollback restored a snapshot —
    // and with it everything else matching feeds.
    onSettled: () => {
      invalidatePurchaseDerived(qc);
    },
  });
  // A plain-string body: outside a DialogProvider `confirm` falls back to
  // `window.confirm`, which drops markup along with the consequences.
  const unlink = async (p: PurchaseRead) => {
    if (p.suspect) {
      const ok = await confirm({
        title: 'Unlink and clear what it copied?',
        body:
          `The colorway, price and purchase date “${p.item_title}” copied onto `
          + `the hat are cleared too, unless you have edited them since. The purchase `
          + 'stays; link it to the right hat from “Needs a hat”.',
        confirmLabel: 'Unlink',
        tone: 'danger',
      });
      if (!ok) return;
    }
    mutation.mutate(p);
  };
  return { unlink, mutation };
}

/**
 * The one link write behind both pick dialogs ("Which hat is this?" and
 * "Which purchase was this hat?"). A link can move a purchase off another
 * hat, so that hat's views refresh as well as this one's.
 */
export function useLinkPurchase(onLinked: () => void) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: ({ purchaseId, link }: { purchaseId: number; link: PurchaseLink; done: string }) =>
      linkPurchase(purchaseId, link),
    onSuccess: (result, { done }) => {
      toast.success(done);
      invalidatePurchaseDerived(qc);
      void invalidateHatViews(qc, result.hat_id);
      if (result.moved_from_hat_id != null) void invalidateHatViews(qc, result.moved_from_hat_id);
      onLinked();
    },
  });
}
