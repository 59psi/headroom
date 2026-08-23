import { apiFetch } from './client';
import type { SharedCollection, SharedHat } from '../types';

/**
 * The collection as an unauthenticated guest sees it.
 *
 * 404s unless the owner has switched guest browsing on — deliberately
 * indistinguishable from an unrouted path, so a stranger cannot learn that
 * this install has the feature and is merely not using it.
 */
export function getGuestCollection(query?: string, colorScope?: string) {
  if (!query) return apiFetch<SharedCollection>('/api/public/guest/collection');
  const qs = new URLSearchParams({ q: query });
  // Omitted when it's the default, so the URL stays readable.
  if (colorScope && colorScope !== 'major') qs.set('color_scope', colorScope);
  return apiFetch<SharedCollection>(`/api/public/guest/collection?${qs}`);
}

/** One hat, same projection as the listing — no wider. */
export function getGuestHat(id: number) {
  return apiFetch<SharedHat>(`/api/public/guest/hat/${id}`);
}
