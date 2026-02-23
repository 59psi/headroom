import { apiFetch } from './client';
import type { SearchResult } from '../types';

export function searchHats(query: string, exactColors = false, roomId?: number) {
  const params = new URLSearchParams({ q: query });
  if (exactColors) params.set('exact_colors', 'true');
  if (roomId) params.set('room_id', String(roomId));
  return apiFetch<SearchResult[]>(`/api/search?${params}`);
}
