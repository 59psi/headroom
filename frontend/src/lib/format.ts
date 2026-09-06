/**
 * Display formatting shared across pages and cards.
 *
 * Each of these existed twice under two names with two output styles —
 * `since()` in the analysis queue card said "4m ago", `formatWhen()` in the
 * backups card said "4 min ago", and the byte formatters disagreed on whether
 * a gigabyte exists. One place, one style.
 */

/** Coarse relative time — a list wants "4 min ago", not a timestamp. */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return 'never';
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return 'just now';
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.floor(hours / 24)} days ago`;
}

/** Binary-prefixed size: "512 B", "3.4 KB", "12.0 MB", "1.25 GB". */
export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}
