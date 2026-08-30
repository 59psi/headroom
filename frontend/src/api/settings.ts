import { apiFetch } from './client';
import type {
  ActivityRow, AnalysisQueueStatus, ApiKeyStatus, ApiKeyTestResult,
  BackupHealth, BackupInfo, BackupUploadStatus, EbayCredsStatus, ImportJob, MdnsStatus, ModelStatus,
  TlsStatus, FrozenPriceRow, PriceReleaseResult, AnalysisFailureGroup,
  RecentError, TagBaseStatus, ConstructionAuditRow, ConstructionClearResult, RepricingStatus,
  ReanalyzeResult, AnalysisJobDetail, CatalogStatus, SharedPriceGroup,
  UnclaimedFromPurchases, RepricingSweepStarted,
} from '../types';

// Re-exported so existing imports from this module keep working; the
// definitions themselves live in ../types with every other API shape.
export type { AnalysisJobRead, AnalysisQueueStatus, BackupHealth } from '../types';

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

export function getTlsStatus() {
  return apiFetch<TlsStatus>('/api/settings/tls');
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

/**
 * The collection as a downloadable zip — `index.html` plus an images folder.
 *
 * A plain URL rather than a fetch: the browser's own download machinery
 * handles the Content-Disposition filename and shows progress, which for a
 * multi-megabyte file beats buffering it in JS to make a blob URL.
 */
export function collectionExportUrl(opts?: {
  title?: string;
  includeValues?: boolean;
  includeDisposed?: boolean;
}): string {
  const p = new URLSearchParams();
  if (opts?.title) p.set('title', opts.title);
  if (opts?.includeValues) p.set('include_values', 'true');
  if (opts?.includeDisposed) p.set('include_disposed', 'true');
  const qs = p.toString();
  return qs ? `/api/admin/collection-export?${qs}` : '/api/admin/collection-export';
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

export function getAnalysisQueue() {
  return apiFetch<AnalysisQueueStatus>('/api/admin/analysis/queue');
}

/** Re-analyze every hat with a photo. Manual prices are protected server-side,
 *  so there is nothing to opt out of. */
export function reanalyzeAll() {
  return apiFetch<ReanalyzeResult>('/api/admin/analysis/reanalyze-all', { method: 'POST' });
}

/**
 * Re-analyze only the hats that FAILED, optionally just one failure group.
 *
 * The alternative was re-running the whole collection to repair a handful of
 * hats a transient 529 knocked over — a Claude call per hat that was already
 * fine. Pass a group's `reason` to narrow further: an overload wants retrying,
 * a response the parser choked on will choke again.
 */
export function retryFailedAnalysis(reason?: string) {
  const qs = reason ? `?reason=${encodeURIComponent(reason)}` : '';
  return apiFetch<ReanalyzeResult>(`/api/admin/analysis/retry-failed${qs}`, {
    method: 'POST',
  });
}

/** What is actually in the colorway catalog — NOT the autocomplete feed.
 *  Reading `len(/api/meta/colorways)` as "models known" once reported 25
 *  regardless of the real total. That feed is no longer capped at 25, but it
 *  is still a bounded autocomplete list and still the wrong thing to count:
 *  a COUNT is the only honest answer to "how big is the catalog". */
export function getColorwayStatus() {
  return apiFetch<CatalogStatus>('/api/admin/colorways/status');
}

/** Kick off the colorway harvest. 202 — the work continues in the background. */
export function refreshColorwayCatalog() {
  return apiFetch<{ started: boolean; detail: string }>(
    '/api/admin/colorways/refresh', { method: 'POST' },
  );
}

/** Whether scheduled backups are actually running — the file list can't say. */
export function getBackupHealth() {
  return apiFetch<BackupHealth>('/api/admin/backups/health');
}

export function getBackupUpload() {
  return apiFetch<BackupUploadStatus>('/api/admin/backups/upload');
}

/** Provider + destination, never a command — see the route's own note. */
export function setBackupUpload(provider: string, destination: string) {
  return apiFetch<BackupUploadStatus>('/api/admin/backups/upload', {
    method: 'PUT',
    body: JSON.stringify({ provider, destination }),
  });
}

export function clearBackupUpload() {
  return apiFetch<BackupUploadStatus>('/api/admin/backups/upload', { method: 'DELETE' });
}

export function testBackupUpload() {
  return apiFetch<{ ok: boolean; detail: string }>(
    '/api/admin/backups/upload/test', { method: 'POST' },
  );
}

// ---------------------------- Physical tags -------------------------- #

/** The host written into QR labels and NFC tags. */
export function getTagBase() {
  return apiFetch<TagBaseStatus>('/api/settings/tags');
}

export function setTagBase(base_url: string) {
  return apiFetch<TagBaseStatus>('/api/settings/tags', {
    method: 'PUT',
    body: JSON.stringify({ base_url }),
  });
}

/** Fall back to whatever host the browser is currently using. */
export function clearTagBase() {
  return apiFetch<void>('/api/settings/tags', { method: 'DELETE' });
}

// ------------------------- Construction audit ------------------------ #

export function auditConstructions() {
  return apiFetch<ConstructionAuditRow[]>('/api/admin/constructions/audit');
}

/**
 * Reassign a construction across every hat carrying it.
 *
 * `to` writes the right answer instead of a blank — the common case is "these
 * are all actually HYDRO", not "I don't know". Null clears the field.
 * `dryRun` reports what would change and writes nothing.
 */
export function clearConstruction(value: string, dryRun: boolean, to?: string | null) {
  const qs = new URLSearchParams({ value, dry_run: String(dryRun) });
  if (to) qs.set('to', to);
  return apiFetch<ConstructionClearResult>(`/api/admin/constructions/clear?${qs}`, {
    method: 'POST',
  });
}

// ---------------------------- Guest browsing ------------------------- #

export function getGuestView() {
  return apiFetch<{ enabled: boolean }>('/api/settings/guest-view');
}

/** Turn unauthenticated read-only browsing on or off. Audited server-side. */
export function setGuestView(enabled: boolean) {
  return apiFetch<{ enabled: boolean }>('/api/settings/guest-view', {
    method: 'PUT',
    body: JSON.stringify({ enabled }),
  });
}

// ---------------------------- Frozen prices --------------------------- #

/** Every active hat whose price is immune to future analysis. */
export function auditFrozenPrices() {
  return apiFetch<FrozenPriceRow[]>('/api/admin/prices/frozen');
}

/**
 * Hand frozen prices back to the live market feed.
 *
 * `dry_run` defaults true server-side and `hatIds` omitted means EVERY frozen
 * hat, so the bare call is the one that changes nothing.
 */
export function releaseFrozenPrices(
  hatIds: number[] | null,
  dryRun: boolean,
  marketPricedOnly = false,
) {
  const qs = new URLSearchParams({
    dry_run: String(dryRun),
    market_priced_only: String(marketPricedOnly),
  });
  if (hatIds) for (const id of hatIds) qs.append('hat_ids', String(id));
  return apiFetch<PriceReleaseResult>(`/api/admin/prices/release?${qs}`, {
    method: 'POST',
  });
}

/** What one run did, hat by hat — the log behind a "Recent runs" row.
 *  Failures sort first, because that is what a finished run gets opened for. */
export function getAnalysisJob(jobId: number) {
  return apiFetch<AnalysisJobDetail>(`/api/admin/analysis/jobs/${jobId}`);
}

/** Resale prices carried by more than a handful of hats at once. */
export function auditSharedPrices() {
  return apiFetch<SharedPriceGroup[]>('/api/admin/prices/shared');
}

/** Sweep the WHOLE collection in the background. Answers 202 immediately;
 *  progress arrives via `getRepricing().progress`. */
export function runRepricingAll() {
  return apiFetch<RepricingSweepStarted>('/api/admin/repricing/run-all', { method: 'POST' });
}

/** What re-running matching would fill in from orders already imported. */
export function getUnclaimedFromPurchases() {
  return apiFetch<UnclaimedFromPurchases>('/api/admin/purchases/unclaimed');
}

/** Why hats are failing analysis, grouped, worst first. */
export function getAnalysisFailures() {
  return apiFetch<AnalysisFailureGroup[]>('/api/admin/analysis/failures');
}

/** Periodic re-pricing status. Appraisals used to move only when a hat was
 *  re-analyzed, so they sat frozen at the date of the last bulk run. */
export function getRepricing() {
  return apiFetch<RepricingStatus>('/api/admin/repricing');
}

/** Sweep now. Available even when the scheduler is off — turning the
 *  background task off shouldn't remove the ability to refresh on purpose. */
export function runRepricing() {
  return apiFetch<{ repriced: number; considered: number; remaining: number }>(
    '/api/admin/repricing/run', { method: 'POST' },
  );
}
