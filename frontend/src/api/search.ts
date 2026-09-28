import { apiFetch, apiFetchWithHeaders } from './client';
import type { ColorSearchResult, PaletteColor, SearchResult, DuplicateGroupRead } from '../types';

/**
 * A text search's answer: the rows, and how many hats matched in all.
 *
 * `GET /api/search` stops at its row cap and reports the uncapped count in
 * `X-Total-Count`, as `GET /api/hats` does. Read without it, a capped list
 * said "50 of 50 results" — the whole answer, as far as anyone could tell,
 * with the newest matches the ones left out.
 */
export interface SearchAnswer {
  results: SearchResult[];
  /** Every match the server counted; the rows' own length when it sent no
   *  count (an older server), which is then all there is to go on. */
  total: number;
}

export async function searchHats(
  query: string, exactColors = false, roomId?: number, colorScope?: string,
): Promise<SearchAnswer> {
  const params = new URLSearchParams({ q: query });
  if (exactColors) params.set('exact_colors', 'true');
  // Omitted at the default so the URL stays readable.
  if (colorScope && colorScope !== 'major') params.set('color_scope', colorScope);
  if (roomId) params.set('room_id', String(roomId));
  const { data, headers } = await apiFetchWithHeaders<SearchResult[]>(`/api/search?${params}`);
  const header = headers.get('X-Total-Count');
  const total = header === null ? NaN : Number(header);
  return { results: data, total: Number.isFinite(total) ? Math.max(total, data.length) : data.length };
}

export function searchHatsByColor(hex: string, roomId?: number, limit = 30) {
  const params = new URLSearchParams({ hex: hex.replace('#', ''), limit: String(limit) });
  if (roomId) params.set('room_id', String(roomId));
  return apiFetch<ColorSearchResult[]>(`/api/search/color?${params}`);
}

export function getColorPalette() {
  return apiFetch<PaletteColor[]>('/api/meta/colors');
}

/** Hats that look like the same hat entered twice. Report only — never mutates. */
export function findDuplicates() {
  return apiFetch<DuplicateGroupRead[]>('/api/search/duplicates');
}
