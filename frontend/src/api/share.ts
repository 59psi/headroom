import { apiFetch } from './client';
import type { SharedCollection } from '../types';

/**
 * The collection as a share link shows it — the same `SharedCollection`
 * projection the guest view serves, reached by token instead of by login.
 * Unauthenticated; a 404 covers expired, revoked and never-issued alike.
 */
export function getSharedCollection(token: string) {
  return apiFetch<SharedCollection>(`/api/public/share/${encodeURIComponent(token)}`);
}
