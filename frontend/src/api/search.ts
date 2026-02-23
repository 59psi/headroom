import { apiFetch } from './client';
import type { SearchResult } from '../types';

export function searchHats(query: string, exactColors = false) {
  const params = new URLSearchParams({ q: query });
  if (exactColors) params.set('exact_colors', 'true');
  return apiFetch<SearchResult[]>(`/api/search?${params}`);
}
