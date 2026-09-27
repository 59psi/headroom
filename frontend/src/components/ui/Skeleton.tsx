import type { CSSProperties } from 'react';

/**
 * Placeholder bars in the shape of what is loading.
 *
 * "Loading…" as a line of text makes a card jump twice: once when the text
 * appears and again when the real content — three times its height — replaces
 * it. A skeleton holds roughly the final shape, so the page settles once.
 *
 * Announced as a single "Loading…" status for assistive tech; the bars
 * themselves are decoration.
 */
export function Skeleton({
  lines = 2,
  height,
  width,
  className = '',
  label = 'Loading…',
}: {
  /** Number of text-line bars. Ignored when `height` is set. */
  lines?: number;
  /** A single block of this height instead of lines (e.g. a metric tile). */
  height?: number | string;
  width?: number | string;
  className?: string;
  label?: string;
}) {
  const block: CSSProperties | undefined = height !== undefined ? { height, width } : undefined;
  return (
    <div className={`hr-skeleton-wrap ${className}`} role="status" aria-live="polite">
      <span className="visually-hidden">{label}</span>
      {block ? (
        <span className="hr-skeleton" style={block} aria-hidden="true" />
      ) : (
        Array.from({ length: lines }, (_, i) => (
          <span
            key={i}
            className="hr-skeleton hr-skeleton-line"
            // The last line runs short, like the end of a paragraph.
            style={{ width: i === lines - 1 && lines > 1 ? '62%' : width }}
            aria-hidden="true"
          />
        ))
      )}
    </div>
  );
}
