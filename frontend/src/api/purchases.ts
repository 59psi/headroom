import { apiFetch } from './client';
import type {
  HatsForPurchase, ImportPreview, ImportResult, MatchResult, PurchaseLink, PurchaseLinkResult,
  PurchaseRead, PurchasesForHat, UnmatchAllResult, UnmatchOneResult,
} from '../types';

/**
 * Purchase history: order line items, and their links to hats.
 *
 * Importing is deliberately two calls. `previewImport` writes nothing and
 * reports what the real call would do; the real call runs the matcher, which
 * sets colorways and cost bases on hats, and the only undo is `unmatchAll`.
 */

export function listPurchases() {
  return apiFetch<PurchaseRead[]>('/api/admin/purchases');
}

/** Dry run. Reports what `importPurchases` would do and changes nothing. */
export function previewImport(items: Record<string, unknown>[]) {
  return apiFetch<ImportPreview>('/api/admin/purchases/import?dry_run=true', {
    method: 'POST',
    body: JSON.stringify({ items }),
  });
}

export function importPurchases(items: Record<string, unknown>[]) {
  return apiFetch<ImportResult>('/api/admin/purchases/import', {
    method: 'POST',
    body: JSON.stringify({ items }),
  });
}

export function rematchPurchases() {
  return apiFetch<MatchResult>('/api/admin/purchases/match', { method: 'POST' });
}

export function unmatchAllPurchases() {
  return apiFetch<UnmatchAllResult>('/api/admin/purchases/unmatch-all', { method: 'POST' });
}

/**
 * Break ONE purchase→hat link. The route existed with no caller: undoing a
 * single wrong match meant unlinking every purchase and re-running the
 * matcher, which is the whole-collection hammer for a one-row mistake.
 */
export function unmatchPurchase(purchaseId: number, opts: { clearCopied?: boolean } = {}) {
  const query = opts.clearCopied ? '?clear_copied=true' : '';
  return apiFetch<UnmatchOneResult>(`/api/admin/purchases/${purchaseId}/unmatch${query}`, {
    method: 'POST',
  });
}

/** Every hat a purchase could be linked to, best fit first (ranked, not filtered). */
export function hatsForPurchase(purchaseId: number) {
  return apiFetch<HatsForPurchase>(`/api/admin/purchases/${purchaseId}/hats`);
}

/** A hat's linked purchase, and every hat purchase it could have instead. */
export function purchasesForHat(hatId: number) {
  return apiFetch<PurchasesForHat>(`/api/admin/purchases/for-hat/${hatId}`);
}

/** Link a purchase to the hat you chose. Fills only the hat's empty fields. */
export function linkPurchase(purchaseId: number, body: PurchaseLink) {
  return apiFetch<PurchaseLinkResult>(`/api/admin/purchases/${purchaseId}/link`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** "Keep": vouch for a link so it is never listed as one to check. */
export function confirmPurchaseLink(purchaseId: number) {
  return apiFetch<PurchaseRead>(`/api/admin/purchases/${purchaseId}/confirm`, { method: 'POST' });
}

/** Unlink every suspect link, clearing the receipt values each copied. */
export function unlinkSuspectPurchases() {
  return apiFetch<UnmatchAllResult>('/api/admin/purchases/unlink-suspect', { method: 'POST' });
}
