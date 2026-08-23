import { apiFetch } from './client';
import type { ColorSearchResult, PaletteColor, SearchResult, DuplicateGroup } from '../types';

export function searchHats(
  query: string, exactColors = false, roomId?: number, colorScope?: string,
) {
  const params = new URLSearchParams({ q: query });
  if (exactColors) params.set('exact_colors', 'true');
  // Omitted at the default so the URL stays readable.
  if (colorScope && colorScope !== 'major') params.set('color_scope', colorScope);
  if (roomId) params.set('room_id', String(roomId));
  return apiFetch<SearchResult[]>(`/api/search?${params}`);
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
  return apiFetch<DuplicateGroup[]>('/api/search/duplicates');
}
