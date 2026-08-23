import { apiFetch } from './client';
import type { SharedCollection, SharedHat } from '../types';

/**
 * The collection as an unauthenticated guest sees it.
 *
 * 404s unless the owner has switched guest browsing on — deliberately
 * indistinguishable from an unrouted path, so a stranger cannot learn that
 * this install has the feature and is merely not using it.
 */
export function getGuestCollection(query?: string) {
  const path = query
    ? `/api/public/guest/collection?q=${encodeURIComponent(query)}`
    : '/api/public/guest/collection';
  return apiFetch<SharedCollection>(path);
}

/** One hat, same projection as the listing — no wider. */
export function getGuestHat(id: number) {
  return apiFetch<SharedHat>(`/api/public/guest/hat/${id}`);
}
