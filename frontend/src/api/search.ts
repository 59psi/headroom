import { apiFetch } from './client';
import type { ColorSearchResult, PaletteColor, SearchResult } from '../types';

export function searchHats(query: string, exactColors = false, roomId?: number) {
  const params = new URLSearchParams({ q: query });
  if (exactColors) params.set('exact_colors', 'true');
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
