import { apiFetch } from './client';
import type { ShareLinkCreated, ShareLinkRead } from '../types';

/**
 * Managing share links — the owner's side. The public view a link opens is
 * `api/share.ts`; these lived in `api/auth.ts`, which they have nothing to do
 * with beyond both being about who may see what.
 */

export function listShareLinks() {
  return apiFetch<ShareLinkRead[]>('/api/share-links');
}

/**
 * `expiresDays` omitted → the server's default (30 days).
 * `expiresDays: null` → never expires, which the caller has to ask for.
 *
 * The distinction is the whole point and this used to erase it: it sent
 * `expires_days: null` unconditionally, so every link the UI created was
 * permanent and the server-side default could never apply. A share link is
 * unscoped and whole-collection — every hat, with photos, and the room and
 * case it lives in — so a forwarded one is a lasting, room-by-room inventory
 * of valuables. That should be a decision, not what happens when you do not
 * make one. `shareLinks.test.ts` pins the request body for each case.
 */
export function createShareLink(label: string, expiresDays?: number | null) {
  return apiFetch<ShareLinkCreated>('/api/share-links', {
    method: 'POST',
    body: JSON.stringify({
      label,
      ...(expiresDays === undefined ? {} : { expires_days: expiresDays }),
    }),
  });
}

export function revokeShareLink(id: number) {
  return apiFetch<void>(`/api/share-links/${id}`, { method: 'DELETE' });
}
