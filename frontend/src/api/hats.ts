import { apiFetch } from './client';
import type { ColorTag, HatRead, MetaOption } from '../types';

/**
 * Matches the `le=` ceiling on `GET /api/hats`.
 *
 * The API defaults to 50 for the benefit of other callers, but every page that
 * uses `listAllHats` filters, totals or shuffles client-side — so a short page
 * doesn't read as "page 1 of n", it reads as hats having disappeared and the
 * collection being worth less than it is.
 */
export const FULL_COLLECTION_LIMIT = 1000;

export function listHats(params?: Record<string, string>) {
  const qs = params ? '?' + new URLSearchParams(params).toString() : '';
  return apiFetch<HatRead[]>(`/api/hats${qs}`);
}

/** Every active hat, for the views that need the whole collection at once. */
export function listAllHats() {
  return listHats({ limit: String(FULL_COLLECTION_LIMIT) });
}

export function getHat(id: number) {
  return apiFetch<HatRead>(`/api/hats/${id}`);
}

export function createHat(data: Record<string, unknown>) {
  return apiFetch<HatRead>('/api/hats', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function updateHat(id: number, data: Record<string, unknown>) {
  return apiFetch<HatRead>(`/api/hats/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export function deleteHat(id: number) {
  return apiFetch<void>(`/api/hats/${id}`, { method: 'DELETE' });
}

export function uploadHatPhoto(id: number, file: File) {
  const form = new FormData();
  form.append('photo', file);
  return apiFetch<HatRead>(`/api/hats/${id}/photo`, {
    method: 'POST',
    body: form,
  });
}

export function reanalyzeHat(id: number) {
  return apiFetch<HatRead>(`/api/hats/${id}/reanalyze`, { method: 'POST' });
}

export function disposeHat(id: number, data: {
  via: string; price?: number | null; to?: string | null; notes?: string | null;
}) {
  return apiFetch<HatRead>(`/api/hats/${id}/dispose`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function undisposeHat(id: number) {
  return apiFetch<HatRead>(`/api/hats/${id}/dispose`, { method: 'DELETE' });
}

export function refreshEbayForHat(id: number) {
  return apiFetch<unknown>(`/api/admin/ebay/refresh/${id}`, { method: 'POST' });
}

export function updateHatColors(id: number, colors: ColorTag[]) {
  return apiFetch<HatRead>(`/api/hats/${id}/colors`, {
    method: 'PUT',
    body: JSON.stringify({ colors }),
  });
}

export function assignHat(id: number, caseId: number | null) {
  return apiFetch<HatRead>(`/api/hats/${id}/assign`, {
    method: 'PATCH',
    body: JSON.stringify({ case_id: caseId }),
  });
}

export function getStyles() {
  return apiFetch<MetaOption[]>('/api/meta/styles');
}

export function getSizes() {
  return apiFetch<MetaOption[]>('/api/meta/sizes');
}

export function getConditions() {
  return apiFetch<MetaOption[]>('/api/meta/conditions');
}
