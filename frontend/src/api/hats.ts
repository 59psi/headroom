import { apiFetch } from './client';
import type { HatRead, MetaOption } from '../types';

export function listHats(params?: Record<string, string>) {
  const qs = params ? '?' + new URLSearchParams(params).toString() : '';
  return apiFetch<HatRead[]>(`/api/hats${qs}`);
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
