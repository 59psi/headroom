import { apiFetch } from './client';
import type { ApiKeyStatus, ApiKeyTestResult } from '../types';

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
