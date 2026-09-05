import { apiFetch, apiFetchWithHeaders } from './client';
import type {
  StyleOption, ColorTag, HatRead, MetaOption } from '../types';

/**
 * Matches the `le=` ceiling on `GET /api/hats`.
 *
 * The API defaults to 50 for the benefit of other callers, but every page that
 * uses `listAllHats` filters, totals or shuffles client-side — so a short page
 * doesn't read as "page 1 of n", it reads as hats having disappeared and the
 * collection being worth less than it is.
 */
export const FULL_COLLECTION_LIMIT = 1000;

/** Backstop against a bad `X-Total-Count` turning this into an infinite loop. */
const MAX_PAGES = 50;

export function listHats(params?: Record<string, string>) {
  const qs = params ? '?' + new URLSearchParams(params).toString() : '';
  return apiFetch<HatRead[]>(`/api/hats${qs}`);
}

/**
 * Every matching hat, following `X-Total-Count` past the server's page cap.
 *
 * The cap is real — `limit` is `le=1000` — so a collection past it came back
 * truncated and the pages that total, filter and shuffle client-side reported
 * a smaller collection worth less money, with nothing on screen saying the
 * list was partial. The server already publishes the true size and logs a
 * warning about exactly this; the header simply had no reader, so the guard
 * detected the problem into a container log nobody was tailing.
 *
 * Paging rather than surfacing a "showing 1000 of N" banner: these callers ask
 * for the whole collection, and a function that promises that should either
 * deliver it or fail — pushing a partial answer to four call sites is how the
 * totals came to be quietly wrong in the first place. The offset walk can in
 * principle skip a row if a hat is inserted mid-burst; that is a far smaller
 * error than dropping everything past the cap, and this is a single-writer app.
 */
async function listEveryHat(params: Record<string, string>): Promise<HatRead[]> {
  const out: HatRead[] = [];
  for (let page = 0; page < MAX_PAGES; page++) {
    const qs = new URLSearchParams({
      ...params,
      limit: String(FULL_COLLECTION_LIMIT),
      offset: String(page * FULL_COLLECTION_LIMIT),
    });
    const { data, headers } = await apiFetchWithHeaders<HatRead[]>(`/api/hats?${qs}`);
    out.push(...data);
    // No header, an empty page, or a short page: nothing more to ask for.
    // Trusting a missing header keeps this working against an older server
    // rather than looping until the backstop.
    const total = Number(headers.get('X-Total-Count'));
    if (!Number.isFinite(total) || data.length === 0 || out.length >= total) break;
  }
  return out;
}

/** Every active hat, for the views that need the whole collection at once. */
export function listAllHats() {
  return listEveryHat({});
}

/**
 * Every disposed hat — what has left the collection.
 *
 * Separate from `listAllHats` because the two answer opposite questions and
 * must never be summed into one figure: these hats are not owned, so they
 * belong in realized proceeds and nowhere near what the collection is worth.
 */
export function listDisposedHats() {
  return listEveryHat({ status: 'disposed' });
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

/** Redo background removal from the retained original photo. */
export function recutHat(id: number) {
  return apiFetch<HatRead>(`/api/hats/${id}/recut`, { method: 'POST' });
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

/**
 * Put a hat in a case, in a room with no case, or nowhere.
 *
 * The two placements are mutually exclusive — the server clears one when it
 * sets the other, because a cased hat's room IS its case's room and a second
 * stored answer is one that can disagree.
 */
export function assignHat(id: number, caseId: number | null, roomId: number | null = null) {
  return apiFetch<HatRead>(`/api/hats/${id}/assign`, {
    method: 'PATCH',
    body: JSON.stringify({ case_id: caseId, room_id: roomId }),
  });
}

export function getStyles() {
  return apiFetch<StyleOption[]>('/api/meta/styles');
}

export function getSizes() {
  return apiFetch<MetaOption[]>('/api/meta/sizes');
}

export function getConditions() {
  return apiFetch<MetaOption[]>('/api/meta/conditions');
}

/**
 * Construction suggestions: the curated list merged with every value already
 * in use. Plain strings, not `MetaOption`s — the field is free text, so there
 * is no value/label split to make.
 */
export function getConstructions() {
  return apiFetch<string[]>('/api/meta/constructions');
}

/**
 * Collection / collaboration names already in use. No curated list — melin
 * names these for the partner or the drop, so any fixed list is wrong by the
 * next release. Duplicates are prevented by these suggestions PLUS
 * server-side canonicalization on write, not by a closed vocabulary.
 */
export function getCollections() {
  return apiFetch<string[]>('/api/meta/collections');
}

/** Log a wear for today. Idempotent server-side (one row per hat per day). */
export function logWear(id: number) {
  return apiFetch<unknown>(`/api/hats/${id}/wear`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

/** Undo the most recent wear entry. */
export function undoLatestWear(id: number) {
  return apiFetch<unknown>(`/api/hats/${id}/wear/latest`, { method: 'DELETE' });
}
