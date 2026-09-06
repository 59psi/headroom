import { apiFetch } from './client';
import type { CaseRead, CaseDetail } from '../types';

export function listCases() {
  return apiFetch<CaseRead[]>('/api/cases');
}

export function getCase(displayId: string) {
  return apiFetch<CaseDetail>(`/api/cases/${displayId}`);
}

/**
 * `roomId` defaults to null, NOT to 1: the server then resolves whichever room
 * carries `is_default`. Any room can hold that flag and the one that does can
 * be changed or deleted, so a hardcoded id both bypasses the default room and
 * can write a `room_id` that no longer exists.
 */
export function createCase(caseType: string, roomId: number | null = null, capacity?: number) {
  return apiFetch<CaseRead>('/api/cases', {
    method: 'POST',
    body: JSON.stringify({ case_type: caseType, room_id: roomId, capacity: capacity ?? null }),
  });
}

export function updateCase(
  displayId: string,
  data: { case_type?: string; room_id?: number; capacity?: number | null },
) {
  return apiFetch<CaseRead>(`/api/cases/${displayId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export function deleteCase(displayId: string) {
  return apiFetch<void>(`/api/cases/${displayId}`, { method: 'DELETE' });
}

