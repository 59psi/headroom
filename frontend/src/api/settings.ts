import { apiFetch } from './client';

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
