import { apiFetch } from './client';
import type { SearchResult } from '../types';

export function searchHats(query: string) {
  return apiFetch<SearchResult[]>(`/api/search?q=${encodeURIComponent(query)}`);
}
