import { apiFetch } from './client';
import type { CaseRead, CaseDetail } from '../types';

export function listCases() {
  return apiFetch<CaseRead[]>('/api/cases');
}

export function getCase(displayId: string) {
  return apiFetch<CaseDetail>(`/api/cases/${displayId}`);
}

export function createCase(caseType: string) {
  return apiFetch<CaseRead>('/api/cases', {
    method: 'POST',
    body: JSON.stringify({ case_type: caseType }),
  });
}

export function updateCase(displayId: string, data: { case_type?: string }) {
  return apiFetch<CaseRead>(`/api/cases/${displayId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export function deleteCase(displayId: string) {
  return apiFetch<void>(`/api/cases/${displayId}`, { method: 'DELETE' });
}

export function uploadCasePhoto(displayId: string, file: File) {
  const form = new FormData();
  form.append('photo', file);
  return apiFetch<CaseRead>(`/api/cases/${displayId}/photo`, {
    method: 'POST',
    body: form,
  });
}
