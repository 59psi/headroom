import { apiFetch } from './client';
import type { ApiKeyStatus, ApiKeyTestResult, MdnsStatus, ModelStatus, RecentError, BackupInfo, ActivityRow, EbayCredsStatus, ImportJob } from '../types';

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

export function getGoogleVisionKeyStatus() {
  return apiFetch<ApiKeyStatus>('/api/settings/google-vision-key');
}

export function setGoogleVisionKey(api_key: string) {
  return apiFetch<ApiKeyStatus>('/api/settings/google-vision-key', {
    method: 'PUT',
    body: JSON.stringify({ api_key }),
  });
}

export function deleteGoogleVisionKey() {
  return apiFetch<void>('/api/settings/google-vision-key', { method: 'DELETE' });
}

export function getModel() {
  return apiFetch<ModelStatus>('/api/settings/model');
}

export function getMdnsStatus() {
  return apiFetch<MdnsStatus>('/api/settings/mdns');
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
export function backupDownloadUrl(includeUploads = true): string {
  return includeUploads ? '/api/admin/backup' : '/api/admin/backup?include_uploads=false';
}

export function inventoryReportUrl(opts?: { includeDisposed?: boolean; includePhotos?: boolean }): string {
  const p = new URLSearchParams();
  if (opts?.includeDisposed) p.set('include_disposed', 'true');
  if (opts?.includePhotos === false) p.set('include_photos', 'false');
  const qs = p.toString();
  return qs ? `/api/admin/inventory-report?${qs}` : '/api/admin/inventory-report';
}

export function getActivityLog(limit = 100, kind?: string) {
  const p = new URLSearchParams({ limit: String(limit) });
  if (kind) p.set('kind', kind);
  return apiFetch<ActivityRow[]>(`/api/admin/activity-log?${p}`);
}

export function getEbayCreds() {
  return apiFetch<EbayCredsStatus>('/api/admin/ebay/creds');
}

export function setEbayCreds(data: { app_id: string; cert_id: string; marketplace?: string }) {
  return apiFetch<EbayCredsStatus>('/api/admin/ebay/creds', {
    method: 'PUT',
    body: JSON.stringify({ marketplace: 'EBAY_US', ...data }),
  });
}

export function deleteEbayCreds() {
  return apiFetch<void>('/api/admin/ebay/creds', { method: 'DELETE' });
}

export function testEbayCreds() {
  return apiFetch<{ ok: boolean; stage: string; detail: string }>(
    '/api/admin/ebay/test', { method: 'POST' },
  );
}

// ---- Bulk import ---- //

export function createImportJob(files: File[], defaults: { case_id?: number | null; condition?: string; size?: string; style?: string }): Promise<{ id: number; total: number; status: string }> {
  const form = new FormData();
  for (const f of files) form.append('photos', f);
  if (defaults.case_id != null) form.append('case_id', String(defaults.case_id));
  if (defaults.condition) form.append('condition', defaults.condition);
  if (defaults.size) form.append('size', defaults.size);
  if (defaults.style) form.append('style', defaults.style);
  return apiFetch('/api/hats/import', { method: 'POST', body: form });
}

export function getImportJob(id: number) {
  return apiFetch<ImportJob>(`/api/hats/import/${id}`);
}

export function listImportJobs(limit = 20) {
  return apiFetch<ImportJob[]>(`/api/hats/import?limit=${limit}`);
}

export function cancelImportJob(id: number) {
  return apiFetch<ImportJob>(`/api/hats/import/${id}`, { method: 'DELETE' });
}
