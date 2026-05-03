import { apiFetch } from './client';
import type { ApiKeyStatus, ApiKeyTestResult, ModelStatus, RecentError, BackupInfo } from '../types';

export function getLogo() {
  return apiFetch<{ logo_path: string | null }>('/api/settings/logo');
}

export function uploadLogo(file: File) {
  const form = new FormData();
  form.append('photo', file);
  return apiFetch<{ logo_path: string | null }>('/api/settings/logo', {
    method: 'POST',
    body: form,
  });
}

export function deleteLogo() {
  return apiFetch<void>('/api/settings/logo', { method: 'DELETE' });
}

export function getApiKeyStatus() {
  return apiFetch<ApiKeyStatus>('/api/settings/api-key');
}

export function setApiKey(api_key: string) {
  return apiFetch<ApiKeyStatus>('/api/settings/api-key', {
    method: 'PUT',
    body: JSON.stringify({ api_key }),
  });
}

export function deleteApiKey() {
  return apiFetch<void>('/api/settings/api-key', { method: 'DELETE' });
}

export function testApiKey() {
  return apiFetch<ApiKeyTestResult>('/api/settings/api-key/test', {
    method: 'POST',
  });
}

export function getModel() {
  return apiFetch<ModelStatus>('/api/settings/model');
}

export function setModel(model_id: string) {
  return apiFetch<ModelStatus>('/api/settings/model', {
    method: 'PUT',
    body: JSON.stringify({ model_id }),
  });
}

export function clearModel() {
  return apiFetch<void>('/api/settings/model', { method: 'DELETE' });
}

export function getRecentErrors(limit = 20) {
  return apiFetch<RecentError[]>(`/api/admin/recent-errors?limit=${limit}`);
}

export function getRecentErrorsCount() {
  return apiFetch<{ count: number }>('/api/admin/recent-errors/count');
}

export function listBackups() {
  return apiFetch<BackupInfo[]>('/api/admin/backups');
}

/** Returns the URL for the on-demand backup download (anchor target). */
export function backupDownloadUrl(): string {
  return '/api/admin/backup';
}
