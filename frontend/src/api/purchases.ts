import { apiFetch } from './client';
import type {
  ImportPreview, ImportResult, MatchResult, PurchaseRow, UnmatchOneResult, UnmatchResult,
} from '../types';

/**
 * Purchase history: order line items, and their links to hats.
 *
 * Importing is deliberately two calls. `previewImport` writes nothing and
 * reports what the real call would do; the real call runs the matcher, which
 * sets colorways and cost bases on hats, and the only undo is `unmatchAll`.
 */

export function listPurchases() {
  return apiFetch<PurchaseRow[]>('/api/admin/purchases');
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
  return apiFetch<UnmatchResult>('/api/admin/purchases/unmatch-all', { method: 'POST' });
}

/**
 * Break ONE purchase→hat link. The route existed with no caller: undoing a
 * single wrong match meant unlinking every purchase and re-running the
 * matcher, which is the whole-collection hammer for a one-row mistake.
 */
export function unmatchPurchase(purchaseId: number) {
  return apiFetch<UnmatchOneResult>(`/api/admin/purchases/${purchaseId}/unmatch`, {
    method: 'POST',
  });
}
